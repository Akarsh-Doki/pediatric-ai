#!/bin/bash
# ============================================================================
# PediatricAI — Wake from Hibernation (restore from snapshot)
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   conda activate pediatricai        # only needed for the fresh-DB fallback (ingest)
#   ./aws-scripts/wake.sh
#
# Restores the database from the snapshot hibernate.sh created (corpus, patients,
# doses all intact — no re-ingest), re-points the ECS task definition at the freshly
# recreated secret, and starts everything. Takes ~10-15 minutes.
# If NO snapshot is found, it falls back to a fresh DB + corpus re-ingest.
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
DB_PASSWORD=$(echo "$SECRET_STRING" | python3 -c "import sys,json; print(json.load(sys.stdin)['DB_PASSWORD'])")
OPENAI_KEY=$(echo "$SECRET_STRING" | python3 -c "import sys,json; print(json.load(sys.stdin)['OPENAI_API_KEY'])")

# 2. Restore the database from the latest hibernation snapshot (data intact).
echo "2/6  Restoring database (5-10 minutes)..."
SNAP_ID=$(aws rds describe-db-snapshots --snapshot-type manual \
  --query "reverse(sort_by(DBSnapshots[?starts_with(DBSnapshotIdentifier,'pediatricai-db-hibernate-')], &SnapshotCreateTime))[0].DBSnapshotIdentifier" \
  --output text --region $REGION 2>/dev/null || echo "None")

if [ "$SNAP_ID" != "None" ] && [ -n "$SNAP_ID" ]; then
  RESTORED_FROM_SNAPSHOT="yes"
  echo "     Restoring from snapshot: $SNAP_ID"
  aws rds restore-db-instance-from-db-snapshot \
    --db-instance-identifier pediatricai-db \
    --db-snapshot-identifier "$SNAP_ID" \
    --db-instance-class db.t4g.micro \
    --db-subnet-group-name pediatricai-db-subnets \
    --vpc-security-group-ids $DB_SG_ID \
    --no-publicly-accessible --no-multi-az \
    --region $REGION > /dev/null 2>&1
else
  RESTORED_FROM_SNAPSHOT="no"
  echo "     No snapshot found — creating a fresh database (corpus will be re-ingested)."
  aws rds create-db-instance --db-instance-identifier pediatricai-db --db-instance-class db.t4g.micro --engine postgres --engine-version 16.4 --master-username pediatricai --master-user-password "$DB_PASSWORD" --allocated-storage 20 --db-name pediatricai --vpc-security-group-ids $DB_SG_ID --db-subnet-group-name pediatricai-db-subnets --no-publicly-accessible --storage-type gp3 --backup-retention-period 0 --no-multi-az --region $REGION > /dev/null 2>&1
fi

echo "     Waiting for database..."
aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
DB_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].Endpoint.Address" --output text --region $REGION)
echo "     Database ready: $DB_ENDPOINT"

# 3. Point the secret at the (possibly new) endpoint; ingest corpus ONLY if fresh.
echo "3/6  Updating secret with DB endpoint..."
aws secretsmanager update-secret --secret-id pediatricai/production --secret-string '{"DATABASE_URL":"postgresql://pediatricai:'"$DB_PASSWORD"'@'"$DB_ENDPOINT"':5432/pediatricai","OPENAI_API_KEY":"'"$OPENAI_KEY"'","LLM_PROVIDER":"openai","DB_PASSWORD":"'"$DB_PASSWORD"'"}' --region $REGION > /dev/null 2>&1

if [ "$RESTORED_FROM_SNAPSHOT" = "no" ]; then
  echo "     Fresh DB — initializing schema and ingesting corpus..."
  MY_IP=$(curl -s ifconfig.me)
  aws ec2 authorize-security-group-ingress --group-id $DB_SG_ID --protocol tcp --port 5432 --cidr "$MY_IP/32" --region $REGION 2>/dev/null || true
  aws rds modify-db-instance --db-instance-identifier pediatricai-db --publicly-accessible --apply-immediately --region $REGION > /dev/null 2>&1
  aws rds wait db-instance-available --db-instance-identifier pediatricai-db --region $REGION
  DB_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].Endpoint.Address" --output text --region $REGION)
  cd "$PROJECT_DIR"
  psql "postgresql://pediatricai:${DB_PASSWORD}@${DB_ENDPOINT}:5432/pediatricai" -f db/init.sql 2>/dev/null
  DATABASE_URL="postgresql://pediatricai:${DB_PASSWORD}@${DB_ENDPOINT}:5432/pediatricai" python -m backend.scripts.ingest_corpus
  aws rds modify-db-instance --db-instance-identifier pediatricai-db --no-publicly-accessible --apply-immediately --region $REGION > /dev/null 2>&1
  aws ec2 revoke-security-group-ingress --group-id $DB_SG_ID --protocol tcp --port 5432 --cidr "$MY_IP/32" --region $REGION 2>/dev/null || true
  DB_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].Endpoint.Address" --output text --region $REGION)
  aws secretsmanager update-secret --secret-id pediatricai/production --secret-string '{"DATABASE_URL":"postgresql://pediatricai:'"$DB_PASSWORD"'@'"$DB_ENDPOINT"':5432/pediatricai","OPENAI_API_KEY":"'"$OPENAI_KEY"'","LLM_PROVIDER":"openai","DB_PASSWORD":"'"$DB_PASSWORD"'"}' --region $REGION > /dev/null 2>&1
  echo "     Corpus ingested; database locked down."
else
  echo "     Restored from snapshot — corpus/doses already present, skipping ingest."
fi

# 4. Recreate ALB
echo "4/6  Creating load balancer..."
ALB_ARN=$(aws elbv2 create-load-balancer --name pediatricai-alb --subnets $SUBNET_IDS_SPACE --security-groups $ALB_SG_ID --region $REGION --query "LoadBalancers[0].LoadBalancerArn" --output text)
aws elbv2 wait load-balancer-available --load-balancer-arns $ALB_ARN --region $REGION
TG_ARN=$(aws elbv2 create-target-group --name pediatricai-tg --protocol HTTP --port 8000 --vpc-id $VPC_ID --target-type ip --health-check-path /health --region $REGION --query "TargetGroups[0].TargetGroupArn" --output text)
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn=$TG_ARN --region $REGION > /dev/null
ALB_DNS=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].DNSName" --output text --region $REGION)
echo "     ALB ready: http://$ALB_DNS"

# 5. Re-point the task definition at the freshly-created secret, then start ECS.
#    hibernate.sh deleted + recreated the secret, so it has a NEW ARN suffix; the existing
#    task definition still references the OLD ARN and would crash the container on startup.
echo "5/6  Re-pointing task def at new secret + starting backend..."
NEW_ARN=$(aws secretsmanager describe-secret --secret-id pediatricai/production --query ARN --output text --region $REGION)
aws ecs describe-task-definition --task-definition pediatricai-backend --query taskDefinition --output json --region $REGION > /tmp/td.json
python3 - "$NEW_ARN" <<'PY'
import json, re, sys
new = sys.argv[1]; td = json.load(open("/tmp/td.json"))
for c in td.get("containerDefinitions", []):
    for sec in c.get("secrets", []):
        m = re.match(r'^(arn:aws:secretsmanager:[^:]+:\d+:secret:.+?-[A-Za-z0-9]{6})(:.*)$', sec["valueFrom"])
        if m:
            sec["valueFrom"] = new + m.group(2)
for k in ["taskDefinitionArn","revision","status","requiresAttributes","compatibilities","registeredAt","registeredBy"]:
    td.pop(k, None)
json.dump(td, open("/tmp/td-new.json","w"))
PY
aws ecs register-task-definition --cli-input-json file:///tmp/td-new.json --region $REGION > /dev/null
aws ecs update-service --cluster pediatricai --service pediatricai-backend --task-definition pediatricai-backend --desired-count 1 --force-new-deployment --region $REGION > /dev/null 2>&1
echo "     Backend starting on the re-pointed task definition."
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