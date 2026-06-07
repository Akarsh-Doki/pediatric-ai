#!/bin/bash
# ============================================================================
# PediatricAI — Hibernate (TRUE $0/month)
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   ./aws-scripts/hibernate.sh
#
# Deletes everything that costs money. Saves secrets to .env.production.bak.
# Cost after: $0.00/month
# To restart: ./aws-scripts/wake.sh (15-20 minutes)
# ============================================================================
set -e

REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."

echo "=== HIBERNATING PediatricAI (scaling to \$0/month) ==="
echo ""

# 0. Save secrets locally before deleting
echo "0/5  Saving secrets locally..."
SECRETS=$(aws secretsmanager get-secret-value --secret-id pediatricai/production --query "SecretString" --output text --region $REGION 2>/dev/null || echo "")
if [ -n "$SECRETS" ]; then
  echo "$SECRETS" > "$PROJECT_DIR/.env.production.bak"
  echo "     Saved to .env.production.bak (DO NOT commit this file)"
  grep -q ".env.production.bak" "$PROJECT_DIR/.gitignore" 2>/dev/null || echo ".env.production.bak" >> "$PROJECT_DIR/.gitignore"
else
  echo "     No secrets found (already deleted)."
fi

# 1. Scale ECS to 0
echo "1/5  Stopping backend..."
aws ecs update-service --cluster pediatricai --service pediatricai-backend --desired-count 0 --region $REGION > /dev/null 2>&1 || true
echo "     Backend stopped."

# 2. Delete ALB
echo "2/5  Removing load balancer..."
ALB_ARN=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].LoadBalancerArn" --output text --region $REGION 2>/dev/null || echo "none")
if [ "$ALB_ARN" != "none" ] && [ "$ALB_ARN" != "None" ]; then
  LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn $ALB_ARN --query "Listeners[0].ListenerArn" --output text --region $REGION 2>/dev/null || echo "none")
  [ "$LISTENER_ARN" != "none" ] && aws elbv2 delete-listener --listener-arn $LISTENER_ARN --region $REGION 2>/dev/null || true
  TG_ARN=$(aws elbv2 describe-target-groups --names pediatricai-tg --query "TargetGroups[0].TargetGroupArn" --output text --region $REGION 2>/dev/null || echo "none")
  [ "$TG_ARN" != "none" ] && aws elbv2 delete-target-group --target-group-arn $TG_ARN --region $REGION 2>/dev/null || true
  aws elbv2 delete-load-balancer --load-balancer-arn $ALB_ARN --region $REGION 2>/dev/null || true
  echo "     ALB removed."
else
  echo "     ALB already removed."
fi

# 3. Delete RDS entirely (saves storage cost too)
echo "3/5  Snapshotting + deleting database..."
DB_EXISTS=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db --query "DBInstances[0].DBInstanceStatus" --output text --region $REGION 2>/dev/null || echo "none")
if [ "$DB_EXISTS" != "none" ] && [ "$DB_EXISTS" != "None" ]; then
  SNAP_ID="pediatricai-db-hibernate-$(date +%Y%m%d-%H%M%S)"
  # --final-db-snapshot-identifier takes the snapshot AS the instance is deleted.
  aws rds delete-db-instance --db-instance-identifier pediatricai-db \
    --final-db-snapshot-identifier "$SNAP_ID" --delete-automated-backups \
    --region $REGION 2>/dev/null || true
  echo "     Snapshot '$SNAP_ID' creating; deletion started."
  # Prune OLDER hibernate snapshots so they don't pile up (keep only this one).
  for OLD in $(aws rds describe-db-snapshots --snapshot-type manual \
        --query "DBSnapshots[?starts_with(DBSnapshotIdentifier,'pediatricai-db-hibernate-') && DBSnapshotIdentifier!='$SNAP_ID'].DBSnapshotIdentifier" \
        --output text --region $REGION 2>/dev/null || true); do
    aws rds delete-db-snapshot --db-snapshot-identifier "$OLD" --region $REGION >/dev/null 2>&1 || true
  done
else
  echo "     Database already deleted; leaving existing snapshot intact."
fi

# 4. Delete secrets from AWS
echo "4/5  Deleting secrets from AWS..."
aws secretsmanager delete-secret --secret-id pediatricai/production --force-delete-without-recovery --region $REGION 2>/dev/null || true
echo "     Secrets deleted (saved locally in .env.production.bak)."

# 5. Empty S3
echo "5/5  Emptying S3..."
BUCKET=$(aws s3api list-buckets --query "Buckets[?starts_with(Name,'pediatricai-frontend')].Name" --output text 2>/dev/null || echo "")
if [ -n "$BUCKET" ]; then
  aws s3 rm s3://$BUCKET --recursive 2>/dev/null || true
  echo "     S3 emptied."
else
  echo "     No S3 bucket found."
fi

echo ""
echo "=== PediatricAI HIBERNATED ==="
echo "Monthly cost: \$0.00"
echo ""
echo "To restart: ./aws-scripts/wake.sh (15-20 min)"
echo "To delete everything permanently: ./aws-scripts/teardown.sh"