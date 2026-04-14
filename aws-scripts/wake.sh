#!/bin/bash
# ============================================================================
# PediatricAI — Wake from Hibernation (restore from $0)
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   conda activate pediatricai
#   ./aws-scripts/wake.sh
#
# NOTE: You need conda activated because this runs the ingestion script.
# Takes ~15-20 minutes. Recreates database, ingests corpus, starts everything.
# ============================================================================
set -e

REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."

echo "=== WAKING PediatricAI ==="
echo ""

# Get resource IDs
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text)
ALB_SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-alb-sg" --query "SecurityGroups[0].GroupId" --output text)
ECS_SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-ecs-sg" --query "SecurityGroups[0].GroupId" --output text)
DB_SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-db-sg" --query "SecurityGroups[0].GroupId" --output text)
SUBNET_IDS_SPACE=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text)

# 1. Recreate secrets
echo "1/6  Recreating secrets..."
if [ -f "$PROJECT_DIR/.env.production.bak" ]; then
  SECRET_STRING=$(cat "$PROJECT_DIR/.env.production.bak")
  aws secretsmanager create-secret --name pediatricai/production --secret-string "$SECRET_STRING" --region $REGION > /dev/null 2>&1 || \
    aws secretsmanager update-secret --secret-id pediatricai/production --secret-string "$SECRET_STRING" --region $REGION > /dev/null 2>&1
  echo "     Secrets restored."
else
  echo "     ERROR: .env.production.bak not found!"
  echo "     Recreate secrets manually (see Phase 10.7 in the deployment guide)."
  exit 1
fi

# 2. Recreate RDS
echo "2/6  Creating database (5-10 minutes)..."
DB_PASSWORD=$(echo "$SECRET_STRING" | python3 -c "import sys,json; print(json.load(sys.stdin)['DB_PASSWORD'])")
aws rds create-db-instance --db-instance-identifier pediatricai-db --db-instance-class db.t4g.micro --engine postgres --engine-version 16.4 --master-username pediatricai --master-user-password "$DB_PASSWORD" --allocated-storage 20 --db-name pediatricai --vpc-security-group-ids $DB_SG_ID --db-subnet-group-name pediatricai-db-subnets --no-publicly-accessible --storage-type gp3 --backup-retention-period 0 --no-multi-az --region $REGION > /dev/null 2>&1
echo "     Waiting for database..."
aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
DB_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].Endpoint.Address" --output text --region $REGION)
echo "     Database ready: $DB_ENDPOINT"

# 3. Initialize DB and ingest corpus
echo "3/6  Initializing database and ingesting corpus..."
MY_IP=$(curl -s ifconfig.me)
aws ec2 authorize-security-group-ingress --group-id $DB_SG_ID --protocol tcp --port 5432 --cidr "$MY_IP/32" --region $REGION 2>/dev/null || true
aws rds modify-db-instance --db-instance-identifier pediatricai-db --publicly-accessible --apply-immediately --region $REGION > /dev/null 2>&1
aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION

DB_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].Endpoint.Address" --output text --region $REGION)

cd "$PROJECT_DIR"
psql "postgresql://pediatricai:${DB_PASSWORD}@${DB_ENDPOINT}:5432/pediatricai" -f db/init.sql 2>/dev/null
DATABASE_URL="postgresql://pediatricai:${DB_PASSWORD}@${DB_ENDPOINT}:5432/pediatricai" python -m backend.scripts.ingest_corpus

# Lock down
aws rds modify-db-instance --db-instance-identifier pediatricai-db --no-publicly-accessible --apply-immediately --region $REGION > /dev/null 2>&1
aws ec2 revoke-security-group-ingress --group-id $DB_SG_ID --protocol tcp --port 5432 --cidr "$MY_IP/32" --region $REGION 2>/dev/null || true

# Update secrets with new endpoint
OPENAI_KEY=$(echo "$SECRET_STRING" | python3 -c "import sys,json; print(json.load(sys.stdin)['OPENAI_API_KEY'])")
aws secretsmanager update-secret --secret-id pediatricai/production --secret-string '{"DATABASE_URL":"postgresql://pediatricai:'"$DB_PASSWORD"'@'"$DB_ENDPOINT"':5432/pediatricai","OPENAI_API_KEY":"'"$OPENAI_KEY"'","LLM_PROVIDER":"openai","DB_PASSWORD":"'"$DB_PASSWORD"'"}' --region $REGION > /dev/null 2>&1
echo "     Database initialized and locked down."

# 4. Recreate ALB
echo "4/6  Creating load balancer..."
ALB_ARN=$(aws elbv2 create-load-balancer --name pediatricai-alb --subnets $SUBNET_IDS_SPACE --security-groups $ALB_SG_ID --region $REGION --query "LoadBalancers[0].LoadBalancerArn" --output text)
aws elbv2 wait load-balancer-available --load-balancer-arns $ALB_ARN --region $REGION
TG_ARN=$(aws elbv2 create-target-group --name pediatricai-tg --protocol HTTP --port 8000 --vpc-id $VPC_ID --target-type ip --health-check-path /health --region $REGION --query "TargetGroups[0].TargetGroupArn" --output text)
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn=$TG_ARN --region $REGION > /dev/null
ALB_DNS=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].DNSName" --output text --region $REGION)
echo "     ALB ready: http://$ALB_DNS"

# 5. Start ECS
echo "5/6  Starting backend..."
aws ecs update-service --cluster pediatricai --service pediatricai-backend --desired-count 1 --region $REGION > /dev/null 2>&1
echo "     Waiting for backend (2 minutes)..."
sleep 120

# 6. Test
echo "6/6  Testing..."
HEALTH=$(curl -s --max-time 10 "http://$ALB_DNS/health" 2>/dev/null || echo "not ready — wait 1 more minute")
echo "     Health: $HEALTH"

echo ""
echo "=== PediatricAI AWAKE ==="
echo "Backend: http://$ALB_DNS"
echo ""
echo "When done: ./aws-scripts/stop.sh"