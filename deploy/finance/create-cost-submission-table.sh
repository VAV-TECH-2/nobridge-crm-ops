#!/usr/bin/env bash
# Creates the CostSubmission table (Operational Tracking) on the running
# finance-db AHEAD of deploying the new image. ADDITIVE + idempotent + safe:
# CREATE TABLE IF NOT EXISTS, no existing table touched. Mirrors the pattern of
# create-exchange-rate-table.sh. Run on the VM BEFORE deploy-finance-image.sh.
set -euo pipefail
cd /home/azureuser/finance

PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
NET=nobridge-finance_default

echo "=== creating CostSubmission table (if not exists) ==="
docker run --rm -i --network "$NET" postgres:17 psql -v ON_ERROR_STOP=1 "$LOCAL" <<'SQL'
CREATE TABLE IF NOT EXISTS "CostSubmission" (
  "id"               TEXT NOT NULL,
  "kind"             TEXT NOT NULL DEFAULT 'cost',
  "title"            TEXT NOT NULL,
  "amount"           DOUBLE PRECISION NOT NULL,
  "currency"         TEXT NOT NULL DEFAULT 'USD',
  "vendor"           TEXT,
  "category"         TEXT,
  "description"      TEXT,
  "occurredOn"       TIMESTAMP(3),
  "submittedBy"      TEXT,
  "status"           TEXT NOT NULL DEFAULT 'pending',
  "invoiceName"      TEXT,
  "invoiceMime"      TEXT,
  "invoiceSize"      INTEGER,
  "invoiceData"      BYTEA,
  "reviewedAt"       TIMESTAMP(3),
  "reviewNote"       TEXT,
  "destination"      TEXT,
  "createdEntryId"   TEXT,
  "createdEntryType" TEXT,
  "createdAt"        TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"        TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "CostSubmission_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "CostSubmission_status_idx" ON "CostSubmission" ("status");
CREATE INDEX IF NOT EXISTS "CostSubmission_createdAt_idx" ON "CostSubmission" ("createdAt");
SQL

echo "=== verify columns ==="
docker run --rm -i --network "$NET" postgres:17 psql "$LOCAL" \
  -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'CostSubmission' ORDER BY ordinal_position;"

echo "=== done — CostSubmission ready ==="
