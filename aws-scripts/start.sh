#!/bin/bash
# ============================================================================
# PediatricAI — Start Everything (before a demo)
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   ./aws-scripts/start.sh
#
# Takes ~5-7 minutes. Handles all states: stopped DB, deleted ALB, 
# target group mismatch, CloudFront origin update.
# Cost while running: ~$0.04/hour = ~$1/day
# ============================================================================
set -e

REGION="us-east-1"

echo "=== Starting PediatricAI ==="
echo ""

# Get resource IDs
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text)
ALB_SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-alb-sg" --query "SecurityGroups[0].GroupId" --output text)
ECS_SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-ecs-sg" --query "SecurityGroups[0].GroupId" --output text)
SUBNET_IDS_SPACE=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text)
SUBNET_IDS_COMMA=$(echo $SUBNET_IDS_SPACE | tr '\t' ',' | tr ' ' ',')

# ==========================================
# 1. START DATABASE
# ==========================================
echo "1/6  Starting database..."
RDS_STATUS=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].DBInstanceStatus" --output text 2>/dev/null || echo "deleted")

if [ "$RDS_STATUS" = "stopped" ]; then
  aws rds start-db-instance --db-instance-identifier pediatricai-db --region $REGION 2>/dev/null || true
  echo "     Waiting for database (3-5 minutes)..."
  aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
  echo "     Database ready."
elif [ "$RDS_STATUS" = "stopping" ]; then
  echo "     Database is still stopping. Waiting..."
  # Wait until it's fully stopped (no direct waiter, so poll)
  while true; do
    STATUS=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].DBInstanceStatus" --output text 2>/dev/null)
    if [ "$STATUS" = "stopped" ]; then break; fi
    sleep 15
  done
  aws rds start-db-instance --db-instance-identifier pediatricai-db --region $REGION
  echo "     Waiting for database (3-5 minutes)..."
  aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
  echo "     Database ready."
elif [ "$RDS_STATUS" = "available" ]; then
  echo "     Database already running."
elif [ "$RDS_STATUS" = "starting" ]; then
  echo "     Database already starting. Waiting..."
  aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
  echo "     Database ready."
elif [ "$RDS_STATUS" = "deleted" ]; then
  echo "     ERROR: Database not found. Run ./aws-scripts/wake.sh instead."
  exit 1
else
  echo "     Database in state: $RDS_STATUS. Waiting for it to become available..."
  aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
  echo "     Database ready."
fi

# ==========================================
# 2. CREATE OR VERIFY ALB
# ==========================================
echo "2/6  Setting up load balancer..."
ALB_EXISTS=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].State.Code" --output text 2>/dev/null || echo "deleted")
if [ "$ALB_EXISTS" = "deleted" ]; then
  echo "     Creating ALB..."
  ALB_ARN=$(aws elbv2 create-load-balancer --name pediatricai-alb --subnets $SUBNET_IDS_SPACE --security-groups $ALB_SG_ID --region $REGION --query "LoadBalancers[0].LoadBalancerArn" --output text)
  aws elbv2 wait load-balancer-available --load-balancer-arns $ALB_ARN --region $REGION
  echo "     ALB created."
else
  ALB_ARN=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].LoadBalancerArn" --output text --region $REGION)
  echo "     ALB already exists."
fi

ALB_DNS=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].DNSName" --output text --region $REGION)
echo "     ALB: http://$ALB_DNS"

# ==========================================
# 3. FRESH TARGET GROUP + LISTENER
# Always recreate to avoid ARN mismatch
# ==========================================
echo "3/6  Setting up target group..."

# Delete old listener if it exists
OLD_LISTENER=$(aws elbv2 describe-listeners --load-balancer-arn $ALB_ARN --query "Listeners[0].ListenerArn" --output text --region $REGION 2>/dev/null || echo "none")
if [ "$OLD_LISTENER" != "none" ] && [ "$OLD_LISTENER" != "None" ]; then
  aws elbv2 delete-listener --listener-arn $OLD_LISTENER --region $REGION 2>/dev/null || true
fi

# Delete old target group if it exists
OLD_TG=$(aws elbv2 describe-target-groups --names pediatricai-tg --query "TargetGroups[0].TargetGroupArn" --output text --region $REGION 2>/dev/null || echo "none")
if [ "$OLD_TG" != "none" ] && [ "$OLD_TG" != "None" ]; then
  aws elbv2 delete-target-group --target-group-arn $OLD_TG --region $REGION 2>/dev/null || true
  sleep 5
fi

# Create fresh target group
TG_ARN=$(aws elbv2 create-target-group --name pediatricai-tg --protocol HTTP --port 8000 --vpc-id $VPC_ID --target-type ip --health-check-path /health --region $REGION --query "TargetGroups[0].TargetGroupArn" --output text)

# Create fresh listener
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn=$TG_ARN --region $REGION > /dev/null
echo "     Target group ready."

# ==========================================
# 4. DELETE OLD ECS SERVICE + CREATE FRESH
# Always recreate to ensure correct target group
# ==========================================
echo "4/6  Starting backend..."

# Delete any existing services (handles both names from previous attempts)
aws ecs delete-service --cluster pediatricai --service pediatricai-backend --force --region $REGION 2>/dev/null || true
aws ecs delete-service --cluster pediatricai --service pediatricai-backend-v2 --force --region $REGION 2>/dev/null || true

# Wait for old services to drain
echo "     Waiting for old services to drain..."
sleep 20

# Create fresh service with correct target group
aws ecs create-service \
  --cluster pediatricai \
  --service-name pediatricai-backend \
  --task-definition pediatricai-backend \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_IDS_COMMA],securityGroups=[$ECS_SG_ID],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=backend,containerPort=8000" \
  --region $REGION > /dev/null 2>&1

echo "     Waiting for backend to start (2-3 minutes)..."
sleep 150

# ==========================================
# 5. UPDATE CLOUDFRONT ORIGIN
# Points CloudFront to the new ALB DNS so 
# the permanent URL keeps working
# ==========================================
echo "5/6  Updating CloudFront origin..."
CF_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[0].Id" --output text 2>/dev/null || echo "none")

if [ "$CF_ID" != "none" ] && [ "$CF_ID" != "None" ]; then
  # Get current config
  CF_CONFIG_FILE="/tmp/cf-config-$$.json"
  aws cloudfront get-distribution-config --id $CF_ID --output json > "$CF_CONFIG_FILE"
  ETAG=$(python3 -c "import json; print(json.load(open('$CF_CONFIG_FILE'))['ETag'])")

  # Update the ALB origin domain to the new ALB DNS
  python3 -c "
import json

with open('$CF_CONFIG_FILE') as f:
    data = json.load(f)

config = data['DistributionConfig']
updated = False
for origin in config['Origins']['Items']:
    domain = origin.get('DomainName', '')
    # Match ALB origins by checking for 'elb.amazonaws.com' or 'alb-backend' id
    if 'elb.amazonaws.com' in domain or origin.get('Id', '') == 'alb-backend':
        origin['DomainName'] = '$ALB_DNS'
        updated = True

if updated:
    with open('/tmp/cf-update.json', 'w') as f:
        json.dump(config, f)
    print('Origin updated to $ALB_DNS')
else:
    print('No ALB origin found in CloudFront — skipping')
    # Write empty marker so we know to skip
    open('/tmp/cf-update-skip', 'w').close()
"

  if [ ! -f /tmp/cf-update-skip ]; then
    aws cloudfront update-distribution --id $CF_ID --if-match $ETAG --distribution-config file:///tmp/cf-update.json > /dev/null 2>&1
    echo "     CloudFront origin updated."
  else
    echo "     No ALB origin in CloudFront (API behaviors not set up yet)."
    rm -f /tmp/cf-update-skip
  fi

  rm -f "$CF_CONFIG_FILE" /tmp/cf-update.json

  CF_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[0].DomainName" --output text)
else
  echo "     No CloudFront distribution found — skipping."
  CF_DOMAIN="(not set up yet)"
fi

# ==========================================
# 6. TEST
# ==========================================
echo "6/6  Testing..."
HEALTH=$(curl -s --max-time 10 "http://$ALB_DNS/health" 2>/dev/null || echo "not ready — wait 1 more minute")
echo "     Health: $HEALTH"

# Try via CloudFront too
if [ "$CF_DOMAIN" != "(not set up yet)" ]; then
  CF_HEALTH=$(curl -s --max-time 10 "https://$CF_DOMAIN/health" 2>/dev/null || echo "CloudFront not ready yet — wait 2 minutes")
  echo "     CloudFront health: $CF_HEALTH"
fi

echo ""
echo "=== PediatricAI LIVE ==="
echo ""
echo "Backend (direct):  http://$ALB_DNS"
echo "Frontend (share):  https://$CF_DOMAIN"
echo ""
echo "Share this URL with recruiters: https://$CF_DOMAIN"
echo ""
echo "When done: ./aws-scripts/stop.sh"