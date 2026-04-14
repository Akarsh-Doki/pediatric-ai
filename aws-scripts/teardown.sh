#!/bin/bash
# ============================================================================
# PediatricAI — PERMANENT TEARDOWN (delete everything)
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   ./aws-scripts/teardown.sh
#
# WARNING: IRREVERSIBLE. Deletes all AWS resources.
# Run when you're done with your job search.
# Cost after: $0/month forever.
# ============================================================================
set -e

REGION="us-east-1"

echo "============================================"
echo "  COMPLETE TEARDOWN — PediatricAI"
echo "============================================"
echo ""
echo "This will DELETE all AWS resources permanently."
echo "Press Ctrl+C within 10 seconds to cancel."
echo ""
for i in $(seq 10 -1 1); do echo -n "$i... "; sleep 1; done
echo ""
echo ""

# 1. ECS
echo "1/9   Deleting ECS..."
aws ecs update-service --cluster pediatricai --service pediatricai-backend --desired-count 0 --region $REGION 2>/dev/null || true
aws ecs delete-service --cluster pediatricai --service pediatricai-backend --force --region $REGION 2>/dev/null || true
sleep 10
aws ecs delete-cluster --cluster pediatricai --region $REGION 2>/dev/null || true
echo "      Done."

# 2. ALB
echo "2/9   Deleting ALB..."
ALB_ARN=$(aws elbv2 describe-load-balancers --names pediatricai-alb --query "LoadBalancers[0].LoadBalancerArn" --output text --region $REGION 2>/dev/null || echo "none")
if [ "$ALB_ARN" != "none" ] && [ "$ALB_ARN" != "None" ]; then
  LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn $ALB_ARN --query "Listeners[0].ListenerArn" --output text --region $REGION 2>/dev/null || echo "none")
  [ "$LISTENER_ARN" != "none" ] && aws elbv2 delete-listener --listener-arn $LISTENER_ARN --region $REGION 2>/dev/null || true
  TG_ARN=$(aws elbv2 describe-target-groups --names pediatricai-tg --query "TargetGroups[0].TargetGroupArn" --output text --region $REGION 2>/dev/null || echo "none")
  [ "$TG_ARN" != "none" ] && aws elbv2 delete-target-group --target-group-arn $TG_ARN --region $REGION 2>/dev/null || true
  aws elbv2 delete-load-balancer --load-balancer-arn $ALB_ARN --region $REGION 2>/dev/null || true
fi
echo "      Done."

# 3. RDS
echo "3/9   Deleting database..."
aws rds delete-db-instance --db-instance-identifier pediatricai-db --skip-final-snapshot --delete-automated-backups --region $REGION 2>/dev/null || true
echo "      Done."

# 4. S3
echo "4/9   Deleting S3..."
BUCKET=$(aws s3api list-buckets --query "Buckets[?starts_with(Name,'pediatricai-frontend')].Name" --output text 2>/dev/null || echo "")
if [ -n "$BUCKET" ]; then
  aws s3 rm s3://$BUCKET --recursive 2>/dev/null || true
  aws s3 rb s3://$BUCKET 2>/dev/null || true
fi
echo "      Done."

# 5. CloudFront
echo "5/9   CloudFront..."
echo "      NOTE: Disable in AWS Console first, wait for 'Deployed', then delete."

# 6. ECR
echo "6/9   Deleting ECR..."
aws ecr delete-repository --repository-name pediatricai-backend --force --region $REGION 2>/dev/null || true
echo "      Done."

# 7. Secrets
echo "7/9   Deleting secrets..."
aws secretsmanager delete-secret --secret-id pediatricai/production --force-delete-without-recovery --region $REGION 2>/dev/null || true
echo "      Done."

# 8. Security groups
echo "8/9   Deleting security groups (may need retry in 5 min)..."
sleep 30
ECS_SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-ecs-sg" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo "none")
ALB_SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-alb-sg" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo "none")
DB_SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=pediatricai-db-sg" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo "none")
[ "$ECS_SG" != "none" ] && aws ec2 delete-security-group --group-id $ECS_SG --region $REGION 2>/dev/null || true
[ "$ALB_SG" != "none" ] && aws ec2 delete-security-group --group-id $ALB_SG --region $REGION 2>/dev/null || true
[ "$DB_SG" != "none" ] && aws ec2 delete-security-group --group-id $DB_SG --region $REGION 2>/dev/null || true
echo "      Done."

# 9. IAM roles + Logs
echo "9/9   Deleting IAM roles and logs..."
aws iam detach-role-policy --role-name pediatricai-ecs-execution --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy 2>/dev/null || true
aws iam delete-role-policy --role-name pediatricai-ecs-execution --policy-name secrets-access 2>/dev/null || true
aws iam delete-role-policy --role-name pediatricai-ecs-execution --policy-name logs-access 2>/dev/null || true
aws iam delete-role --role-name pediatricai-ecs-execution 2>/dev/null || true
aws iam delete-role --role-name pediatricai-ecs-task 2>/dev/null || true
aws logs delete-log-group --log-group-name /ecs/pediatricai-backend --region $REGION 2>/dev/null || true
echo "      Done."

echo ""
echo "============================================"
echo "  TEARDOWN COMPLETE"
echo "============================================"
echo "Check AWS Console > Billing in 24 hours."
echo "Also revoke your OpenAI key at platform.openai.com/api-keys"