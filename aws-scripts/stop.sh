#!/bin/bash
# ============================================================================
# PediatricAI — Quick Stop (after a demo)
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   ./aws-scripts/stop.sh
#
# Takes ~30 seconds. Stops backend, deletes ALB, stops database.
# Cost after: ~$0.50/month
# To restart: ./aws-scripts/start.sh (5 minutes)
# For TRUE $0: ./aws-scripts/hibernate.sh
# ============================================================================
set -e

REGION="us-east-1"

echo "=== Stopping PediatricAI ==="
echo ""

# 1. Scale ECS to 0
echo "1/3  Stopping backend containers..."
aws ecs update-service --cluster pediatricai --service pediatricai-backend --desired-count 0 --region $REGION > /dev/null 2>&1 || true
echo "     Backend stopped."

# 2. Delete ALB (biggest idle cost — ~$16/month)
echo "2/3  Removing load balancer..."
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

# 3. Stop RDS
echo "3/3  Stopping database..."
aws rds stop-db-instance --db-instance-identifier pediatricai-db --region $REGION 2>/dev/null || true
echo "     Database stopping (takes a few minutes in background)."

echo ""
echo "=== PediatricAI STOPPED ==="
echo "Ongoing cost: ~\$0.50/month (Secrets Manager + RDS storage)"
echo ""
echo "To restart:        ./aws-scripts/start.sh (5 min)"
echo "For TRUE \$0/month: ./aws-scripts/hibernate.sh"
echo "Check status:      ./aws-scripts/status.sh"