#!/usr/bin/env bash
# !!! HISTORICAL — predates the 2026-10-01 unification. It rebuilds the CRM from
# scratch (fresh APP_SECRET + DB password) with an apex-only crm.nobridge.co
# Caddyfile, which would also drop Finance (/finance), Ops (/ops), AI Access and
# every old-host forward. Do not run it as a "rollback". Current state:
#   SERVER_URL/FRONTEND_URL = https://app.nobridge.co (Google callbacks stay on crm.)
#   Caddy                   = deploy/Caddyfile.unified
#   undo the unification    = deploy/unify/rollback.sh
set -euo pipefail

TS=$(date +%Y%m%d-%H%M%S)
DEPLOY=/home/azureuser/twenty
cd "$DEPLOY"

echo "===[1/8] Backup current files==="
mkdir -p "backup-$TS"
cp -p docker-compose.yml "backup-$TS/" 2>/dev/null || true
cp -p .env "backup-$TS/" 2>/dev/null || true
sudo cp -p /etc/caddy/Caddyfile "backup-$TS/Caddyfile" 2>/dev/null || true
chown -R azureuser:azureuser "backup-$TS"
ls -la "backup-$TS"

echo "===[2/8] Harvest OAuth creds from old .env (NOT printed)==="
SAVED_GOOGLE_ID=$(grep -E '^AUTH_GOOGLE_CLIENT_ID=' .env | cut -d= -f2-)
SAVED_GOOGLE_SECRET=$(grep -E '^AUTH_GOOGLE_CLIENT_SECRET=' .env | cut -d= -f2-)
test -n "$SAVED_GOOGLE_ID" || { echo "FATAL: AUTH_GOOGLE_CLIENT_ID missing"; exit 1; }
test -n "$SAVED_GOOGLE_SECRET" || { echo "FATAL: AUTH_GOOGLE_CLIENT_SECRET missing"; exit 1; }
echo "Google creds harvested (Client ID length: ${#SAVED_GOOGLE_ID})"

echo "===[3/8] Stop containers + drop volumes==="
sudo docker compose down --volumes --remove-orphans

echo "===[4/8] Remove obsolete images==="
sudo docker image rm twenty-custom:latest 2>/dev/null || echo "  twenty-custom:latest already gone"
sudo docker image rm twentycrm/twenty:latest 2>/dev/null || echo "  twentycrm/twenty:latest already gone"
sudo docker image prune -f

echo "===[5/8] Mint fresh secrets + write .env==="
NEW_APP_SECRET=$(openssl rand -hex 32)
NEW_PG_PW=$(openssl rand -hex 24)
cat > .env <<EOF
TAG=v2.7.3
SERVER_URL=https://crm.nobridge.co
FRONTEND_URL=https://crm.nobridge.co
IS_MULTIWORKSPACE_ENABLED=false
IS_SIGN_UP_DISABLED=false
APP_SECRET=$NEW_APP_SECRET
PG_DATABASE_USER=postgres
PG_DATABASE_PASSWORD=$NEW_PG_PW
PG_DATABASE_HOST=db
PG_DATABASE_PORT=5432
STORAGE_TYPE=local
REDIS_URL=redis://redis:6379
MESSAGING_PROVIDER_GMAIL_ENABLED=true
CALENDAR_PROVIDER_GOOGLE_ENABLED=true
AUTH_GOOGLE_CLIENT_ID=$SAVED_GOOGLE_ID
AUTH_GOOGLE_CLIENT_SECRET=$SAVED_GOOGLE_SECRET
AUTH_GOOGLE_CALLBACK_URL=https://crm.nobridge.co/auth/google/redirect
AUTH_GOOGLE_APIS_CALLBACK_URL=https://crm.nobridge.co/auth/google-apis/get-access-token
EOF
chmod 600 .env
chown azureuser:azureuser .env
echo ".env written ($(wc -l < .env) lines)"

echo "===[6/8] Write apex-only docker-compose.yml==="
cat > docker-compose.yml <<'COMPOSE_EOF'
name: twenty

services:
  server:
    image: twentycrm/twenty:${TAG:-v2.7.3}
    volumes:
      - server-local-data:/app/packages/twenty-server/.local-storage
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      NODE_PORT: 3000
      PG_DATABASE_URL: postgres://${PG_DATABASE_USER}:${PG_DATABASE_PASSWORD}@${PG_DATABASE_HOST:-db}:${PG_DATABASE_PORT:-5432}/default
      SERVER_URL: ${SERVER_URL}
      FRONTEND_URL: ${FRONTEND_URL}
      REDIS_URL: ${REDIS_URL:-redis://redis:6379}
      DISABLE_DB_MIGRATIONS: "false"
      DISABLE_CRON_JOBS_REGISTRATION: "false"
      STORAGE_TYPE: ${STORAGE_TYPE:-local}
      APP_SECRET: ${APP_SECRET}
      IS_SIGN_UP_DISABLED: ${IS_SIGN_UP_DISABLED:-false}
      IS_MULTIWORKSPACE_ENABLED: "false"
      # Disable third-party company-logo fetches to twenty-icons.com.
      # Prevents the per-company favicon flood + O(n^2) avatar re-render storm
      # that crashed the Companies view ("Aw, Snap!"). Companies show initials.
      ALLOW_REQUESTS_TO_TWENTY_ICONS: "false"
      MESSAGING_PROVIDER_GMAIL_ENABLED: ${MESSAGING_PROVIDER_GMAIL_ENABLED:-true}
      CALENDAR_PROVIDER_GOOGLE_ENABLED: ${CALENDAR_PROVIDER_GOOGLE_ENABLED:-true}
      AUTH_GOOGLE_ENABLED: "true"
      AUTH_GOOGLE_CLIENT_ID: ${AUTH_GOOGLE_CLIENT_ID}
      AUTH_GOOGLE_CLIENT_SECRET: ${AUTH_GOOGLE_CLIENT_SECRET}
      AUTH_GOOGLE_CALLBACK_URL: ${AUTH_GOOGLE_CALLBACK_URL}
      AUTH_GOOGLE_APIS_CALLBACK_URL: ${AUTH_GOOGLE_APIS_CALLBACK_URL}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: curl --fail http://localhost:3000/healthz
      interval: 5s
      timeout: 5s
      retries: 20
    restart: always

  worker:
    image: twentycrm/twenty:${TAG:-v2.7.3}
    volumes:
      - server-local-data:/app/packages/twenty-server/.local-storage
    command: ["yarn", "worker:prod"]
    environment:
      PG_DATABASE_URL: postgres://${PG_DATABASE_USER}:${PG_DATABASE_PASSWORD}@${PG_DATABASE_HOST:-db}:${PG_DATABASE_PORT:-5432}/default
      SERVER_URL: ${SERVER_URL}
      FRONTEND_URL: ${FRONTEND_URL}
      REDIS_URL: ${REDIS_URL:-redis://redis:6379}
      DISABLE_DB_MIGRATIONS: "true"
      DISABLE_CRON_JOBS_REGISTRATION: "true"
      STORAGE_TYPE: ${STORAGE_TYPE:-local}
      APP_SECRET: ${APP_SECRET}
      IS_MULTIWORKSPACE_ENABLED: "false"
      MESSAGING_PROVIDER_GMAIL_ENABLED: ${MESSAGING_PROVIDER_GMAIL_ENABLED:-true}
      CALENDAR_PROVIDER_GOOGLE_ENABLED: ${CALENDAR_PROVIDER_GOOGLE_ENABLED:-true}
      AUTH_GOOGLE_ENABLED: "true"
      AUTH_GOOGLE_CLIENT_ID: ${AUTH_GOOGLE_CLIENT_ID}
      AUTH_GOOGLE_CLIENT_SECRET: ${AUTH_GOOGLE_CLIENT_SECRET}
      AUTH_GOOGLE_CALLBACK_URL: ${AUTH_GOOGLE_CALLBACK_URL}
      AUTH_GOOGLE_APIS_CALLBACK_URL: ${AUTH_GOOGLE_APIS_CALLBACK_URL}
    depends_on:
      db:
        condition: service_healthy
      server:
        condition: service_healthy
    restart: always

  db:
    image: postgres:16
    volumes:
      - db-data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: default
      POSTGRES_PASSWORD: ${PG_DATABASE_PASSWORD}
      POSTGRES_USER: ${PG_DATABASE_USER}
    healthcheck:
      test: pg_isready -U ${PG_DATABASE_USER} -h localhost -d postgres
      interval: 5s
      timeout: 5s
      retries: 10
    restart: always

  redis:
    image: redis:7
    restart: always
    command: ["--maxmemory-policy", "noeviction"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  db-data:
  server-local-data:
COMPOSE_EOF
chown azureuser:azureuser docker-compose.yml
echo "docker-compose.yml written"

echo "===[7/8] Apex-only Caddyfile + reload==="
sudo tee /etc/caddy/Caddyfile > /dev/null <<'CADDY_EOF'
crm.nobridge.co {
    encode zstd gzip

    @assets path /assets/*
    header @assets Cache-Control "public, max-age=31536000, immutable"

    @fonts path /fonts/*
    header @fonts Cache-Control "public, max-age=31536000, immutable"

    @images path /images/*
    header @images Cache-Control "public, max-age=86400"

    reverse_proxy 127.0.0.1:3000
}
CADDY_EOF
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
systemctl is-active caddy

echo "===[8/8] Pull + start + wait healthy==="
sudo docker compose pull
sudo docker compose up -d

for i in $(seq 1 60); do
    STATE=$(sudo docker inspect twenty-server-1 --format '{{.State.Health.Status}}' 2>/dev/null || echo "starting")
    echo "[$i/60] server=$STATE"
    if [ "$STATE" = "healthy" ]; then break; fi
    sleep 5
done

echo "===FINAL STATE==="
sudo docker compose ps
echo "---SERVER LOG (tail 40, filtered)---"
sudo docker compose logs server --tail 200 2>&1 | grep -iE "error|crash|listen|ready|migrat|nest" | tail -40 || true
echo "===DONE==="
