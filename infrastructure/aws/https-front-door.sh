#!/usr/bin/env bash
# HTTPS front door for the staging API — SOLUSDEV-96 / INFRA-01.
#
# WHY A SCRIPT AND NOT TERRAFORM. There is no IaC in this repo: the VPC, ALB,
# target group, ECS cluster/service and RDS instance were all created in the
# console. Introducing Terraform here would mean either importing all of that
# (a project in itself) or running two sources of truth. So this formalises the
# existing convention instead: idempotent AWS CLI, committed and reviewable,
# safe to re-run. If the team later adopts Terraform, this file is the spec.
#
# IDEMPOTENT BY CONSTRUCTION. Every step checks for the resource first. Running
# it twice changes nothing the second time.
#
# WHAT IT DOES NOT DO. It never creates the ACM certificate (that needs a domain
# and manual DNS validation on Google Cloud DNS) and never writes secrets. Both
# are human steps — see `HUMAN-STEPS.md`.
#
#   ./https-front-door.sh network     # security groups + wiring   (no domain needed)
#   ./https-front-door.sh listener    # 443 + 80->443 redirect      (needs CERT_ARN)
#   ./https-front-door.sh taskdef     # register taskdef.json + point the service at it
#   ./https-front-door.sh status      # report current state
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
VPC="${SOLUS_VPC:-vpc-0e40982138d7f824c}"
ALB_NAME="${SOLUS_ALB_NAME:-solus-sload-balancer}"
TG_NAME="${SOLUS_TG_NAME:-sol-staging}"
CLUSTER="${SOLUS_ECS_CLUSTER:-solus-cluster}"
SERVICE="${SOLUS_ECS_SERVICE:-solus-api-staging}"
# Already exists and is ALREADY TRUSTED BY RDS (solus-staging-rds-sg allows 5432
# only from this group). The ECS service is currently on the DEFAULT VPC group
# instead, which is why the API cannot reach its database.
APP_SG_NAME="${SOLUS_APP_SG_NAME:-solus-staging-services-sg}"
ALB_SG_NAME="${SOLUS_ALB_SG_NAME:-solus-staging-alb-sg}"
CONTAINER_PORT=8000

export AWS_PAGER=""
aws() { command aws --region "$REGION" "$@"; }
log() { printf '  %s\n' "$*"; }

sg_id() { aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=$1" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null; }

alb_arn() { aws elbv2 describe-load-balancers --names "$ALB_NAME" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text; }

tg_arn() { aws elbv2 describe-target-groups --names "$TG_NAME" \
  --query 'TargetGroups[0].TargetGroupArn' --output text; }

# ---------------------------------------------------------------- network

cmd_network() {
  echo "==> security groups"
  local alb_sg app_sg
  alb_sg="$(sg_id "$ALB_SG_NAME")"
  if [ "$alb_sg" = "None" ] || [ -z "$alb_sg" ]; then
    alb_sg="$(aws ec2 create-security-group --group-name "$ALB_SG_NAME" --vpc-id "$VPC" \
      --description "Solus staging ALB: public 80/443" --query GroupId --output text)"
    log "created $ALB_SG_NAME ($alb_sg)"
  else
    log "$ALB_SG_NAME exists ($alb_sg)"
  fi

  # The ALB is the ONLY thing the internet may talk to.
  for port in 80 443; do
    if aws ec2 authorize-security-group-ingress --group-id "$alb_sg" --protocol tcp \
        --port "$port" --cidr 0.0.0.0/0 >/dev/null 2>&1; then
      log "opened $port/tcp from 0.0.0.0/0"
    else
      log "$port/tcp already open"
    fi
  done

  app_sg="$(sg_id "$APP_SG_NAME")"
  [ "$app_sg" != "None" ] && [ -n "$app_sg" ] || { echo "missing $APP_SG_NAME" >&2; exit 1; }
  # The task accepts 8000 ONLY from the ALB's group. Without this the plain-HTTP
  # path stays open to anything in the VPC and the TLS is decorative.
  if aws ec2 authorize-security-group-ingress --group-id "$app_sg" --protocol tcp \
      --port "$CONTAINER_PORT" --source-group "$alb_sg" >/dev/null 2>&1; then
    log "opened $CONTAINER_PORT/tcp on $APP_SG_NAME from $ALB_SG_NAME only"
  else
    log "$CONTAINER_PORT/tcp from ALB already allowed"
  fi

  echo "==> move the ALB onto its own group"
  aws elbv2 set-security-groups --load-balancer-arn "$(alb_arn)" \
    --security-groups "$alb_sg" --query 'SecurityGroupIds' --output text
  log "ALB -> $ALB_SG_NAME"

  echo "==> move the ECS service onto the app group"
  # assignPublicIp stays ENABLED: there is no NAT gateway and no VPC endpoints,
  # so the task needs a public IP to pull from ECR and reach Secrets Manager and
  # CloudWatch. That is not an exposure — the security group above is what makes
  # it unreachable. Removing the IP would cost a NAT gateway (~$32/mo) and buy
  # nothing.
  local subnets
  subnets="$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
    --query 'services[0].networkConfiguration.awsvpcConfiguration.subnets' --output text | tr '\t' ',')"
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
    --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$app_sg],assignPublicIp=ENABLED}" \
    --query 'service.serviceName' --output text
  log "service -> $APP_SG_NAME (this also restores its route to RDS)"
}

# --------------------------------------------------------------- listener

cmd_listener() {
  : "${CERT_ARN:?set CERT_ARN to the issued ACM certificate ARN}"
  local arn tg
  arn="$(alb_arn)"; tg="$(tg_arn)"

  echo "==> HTTPS:443"
  local https_arn
  https_arn="$(aws elbv2 describe-listeners --load-balancer-arn "$arn" \
    --query 'Listeners[?Port==`443`].ListenerArn' --output text)"
  if [ -z "$https_arn" ]; then
    aws elbv2 create-listener --load-balancer-arn "$arn" --protocol HTTPS --port 443 \
      --certificates "CertificateArn=$CERT_ARN" \
      --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
      --default-actions "Type=forward,TargetGroupArn=$tg" \
      --query 'Listeners[0].ListenerArn' --output text
    log "created HTTPS listener"
  else
    log "HTTPS listener exists ($https_arn)"
  fi

  echo "==> HTTP:80 -> 443 redirect"
  local http_arn
  http_arn="$(aws elbv2 describe-listeners --load-balancer-arn "$arn" \
    --query 'Listeners[?Port==`80`].ListenerArn' --output text)"
  # 301, not 302: the redirect is permanent and we want it cached.
  aws elbv2 modify-listener --listener-arn "$http_arn" \
    --default-actions 'Type=redirect,RedirectConfig={Protocol=HTTPS,Port=443,StatusCode=HTTP_301}' \
    --query 'Listeners[0].DefaultActions[0].Type' --output text
  log "80 now redirects to 443"
}

# ----------------------------------------------------------------- status

cmd_status() {
  local arn; arn="$(alb_arn)"
  echo "ALB       : $(aws elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[0].DNSName' --output text)"
  echo "ALB SGs   : $(aws elbv2 describe-load-balancers --names "$ALB_NAME" --query 'LoadBalancers[0].SecurityGroups' --output text)"
  echo "Listeners : $(aws elbv2 describe-listeners --load-balancer-arn "$arn" --query 'Listeners[].[Port,Protocol,DefaultActions[0].Type]' --output text | tr '\n' ' ')"
  echo "Svc SGs   : $(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --query 'services[0].networkConfiguration.awsvpcConfiguration.securityGroups' --output text)"
  echo "Targets   : $(aws elbv2 describe-target-health --target-group-arn "$(tg_arn)" --query 'TargetHealthDescriptions[].TargetHealth.State' --output text)"
}

# ------------------------------------------------------------- taskdef
#
# THE REASON STAGING HAS BEEN BROKEN. CI deploys with `update-service
# --force-new-deployment`, which re-pulls the image but NEVER registers a task
# definition — so `taskdef.json` has never been applied and the service still
# runs `solus-api:1`, hand-made in the console with variable names the code does
# not read (`DB_HOST` vs `SOLUS_DATABASE_URL`). The app therefore falls back to
# its localhost default and alembic dies with
# `ConnectionRefusedError ('127.0.0.1', 5432)` at boot.
#
# It only LOOKED healthy because a container from an older image had been
# running since July and was never restarted.

cmd_taskdef() {
  local file="${TASKDEF:-$(dirname "$0")/taskdef.json}"
  # Refuse rather than register something that cannot boot: a task definition
  # with a placeholder ARN would crash-loop exactly like today.
  if grep -q "REPLACE_ME\|XXXXXX" "$file"; then
    cat >&2 <<'EOF'
refusing to register: taskdef.json still contains a placeholder secret ARN.

Create the Supabase secret and add the composed DSN first — see HUMAN-STEPS.md:
  - secret  solus/staging/supabase   key jwt_secret
  - add key database_url to the existing solus/staging/db

Then replace the placeholder ARN in taskdef.json and re-run.
EOF
    exit 1
  fi
  local arn
  arn="$(aws ecs register-task-definition --cli-input-json "file://$file"     --query 'taskDefinition.taskDefinitionArn' --output text)"
  log "registered $arn"
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE"     --task-definition "$arn" --query 'service.taskDefinition' --output text
  log "service now points at the registered definition"
}

case "${1:-status}" in
  network) cmd_network ;;
  taskdef) cmd_taskdef ;;
  listener) cmd_listener ;;
  status) cmd_status ;;
  *) echo "usage: $0 {network|taskdef|listener|status}" >&2; exit 2 ;;
esac
