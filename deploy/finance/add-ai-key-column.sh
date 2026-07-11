#!/usr/bin/env bash
# Adds the anthropicApiKey column to finance-db ahead of deploying the new image.
# Idempotent + safe: the currently-running app doesn't reference it.
set -u
cd /home/azureuser/finance
PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
NET=nobridge-finance_default
docker run --rm --network "$NET" postgres:17 psql "$LOCAL" -c 'ALTER TABLE "AppSettings" ADD COLUMN IF NOT EXISTS "anthropicApiKey" TEXT;'
echo "--- AppSettings columns (anthropic) ---"
docker run --rm --network "$NET" postgres:17 psql "$LOCAL" -t -A -c "select column_name, data_type from information_schema.columns where table_name='AppSettings' and column_name='anthropicApiKey';"
