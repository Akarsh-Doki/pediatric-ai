#!/bin/bash
# ============================================================================
# PediatricAI — Start Everything (before a demo)
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   ./aws-scripts/start.sh
#
# Takes ~5 minutes. Starts database, creates ALB, starts backend.
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

# 1. Start database
echo "1/4  Starting database..."
aws rds start-db-instance --db-instance-identifier pediatricai-db --region $REGION 2>/dev/null || true
echo "     Waiting for database (3-5 minutes)..."
aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
echo "     Database ready."

# 2. Recreate ALB (if it was deleted by stop.sh)
ALB_EXISTS=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].State.Code" --output text 2>/dev/null || echo "deleted")
if [ "$ALB_EXISTS" = "deleted" ]; then
  echo "2/4  Creating load balancer..."
  ALB_ARN=$(aws elbv2 create-load-balancer --name pediatricai-alb --subnets $SUBNET_IDS_SPACE --security-groups $ALB_SG_ID --region $REGION --query "LoadBalancers[0].LoadBalancerArn" --output text)
  aws elbv2 wait load-balancer-available --load-balancer-arns $ALB_ARN --region $REGION

  TG_ARN=$(aws elbv2 create-target-group --name pediatricai-tg --protocol HTTP --port 8000 --vpc-id $VPC_ID --target-type ip --health-check-path /health --region $REGION --query "TargetGroups[0].TargetGroupArn" --output text)

  aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn=$TG_ARN --region $REGION > /dev/null
else
  echo "2/4  ALB already exists."
  TG_ARN=$(aws elbv2 describe-target-groups --names pediatricai-tg --query "TargetGroups[0].TargetGroupArn" --output text --region $REGION)
fi

ALB_DNS=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].DNSName" --output text --region $REGION)
echo "     ALB: http://$ALB_DNS"

# 3. Start ECS
echo "3/4  Starting backend..."
aws ecs update-service --cluster pediatricai --service pediatricai-backend --desired-count 1 --region $REGION > /dev/null 2>&1
echo "     Waiting for backend (2-3 minutes)..."
sleep 120

# 4. Test
echo "4/4  Testing..."
HEALTH=$(curl -s --max-time 10 "http://$ALB_DNS/health" 2>/dev/null || echo "not ready — wait 1 more minute and try: curl http://$ALB_DNS/health")
echo "     Health: $HEALTH"

echo ""
echo "=== PediatricAI LIVE ==="
echo "Backend: http://$ALB_DNS"
echo ""
echo "When done: ./aws-scripts/stop.sh"