#!/bin/bash
# ============================================================================
# PediatricAI — Check Status
#
# TO RUN:
#   cd ~/Desktop/pediatric-ai
#   ./aws-scripts/status.sh
#
# Shows what's running and estimated current cost.
# ============================================================================

echo "=== PediatricAI Status ==="
echo ""

# ECS
RUNNING=$(aws ecs describe-services --cluster pediatricai --services pediatricai-backend \
  --query "services[0].runningCount" --output text 2>/dev/null || echo "not found")
echo "ECS Containers:  $RUNNING running"

# ALB
ALB_STATUS=$(aws elbv2 describe-load-balancers --names pediatricai-alb \
  --query "LoadBalancers[0].State.Code" --output text 2>/dev/null || echo "deleted")
echo "ALB:             $ALB_STATUS"

# RDS
RDS_STATUS=$(aws rds describe-db-instances --db-instance-identifier pediatricai-db \
  --query "DBInstances[0].DBInstanceStatus" --output text 2>/dev/null || echo "deleted")
echo "RDS Database:    $RDS_STATUS"

# ALB DNS
ALB_DNS=$(aws elbv2 describe-load-balancers --names pediatricai-alb \
  --query "LoadBalancers[0].DNSName" --output text 2>/dev/null || echo "none")

# Health check
if [ "$ALB_DNS" != "none" ] && [ "$RUNNING" = "1" ]; then
  HEALTH=$(curl -s --max-time 5 "http://$ALB_DNS/health" 2>/dev/null || echo "not responding")
  echo "Health:          $HEALTH"
  echo "Backend URL:     http://$ALB_DNS"
fi

# Cost estimate
echo ""
echo "=== Estimated Current Cost ==="
if [ "$RUNNING" = "1" ] && [ "$ALB_STATUS" = "active" ] && [ "$RDS_STATUS" = "available" ]; then
  echo "Everything ON:   ~\$0.04/hour = ~\$1/day"
elif [ "$RUNNING" = "0" ] && [ "$ALB_STATUS" = "active" ]; then
  echo "ECS off, ALB on: ~\$0.02/hour = ~\$0.50/day"
elif [ "$ALB_STATUS" = "deleted" ] && [ "$RDS_STATUS" = "stopped" ]; then
  echo "Stopped:         ~\$0.50/month"
elif [ "$ALB_STATUS" = "deleted" ] && [ "$RDS_STATUS" = "deleted" ]; then
  echo "Hibernated:      ~\$0.00/month"
else
  echo "Mixed state — check above"
fi
echo ""