#!/usr/bin/env bash
# Adds the Invoice-Management / payment-tracking columns to CostSubmission on the
# running finance-db AHEAD of deploying the new image. ADDITIVE + idempotent +
# safe: ADD COLUMN IF NOT EXISTS only, no existing column touched, so the
# currently-running app keeps working (it just ignores the new columns until the
# new image ships). Mirrors add-ai-key-column.sh. Run on the VM BEFORE
# deploy-finance-image.sh.
set -euo pipefail
cd /home/azureuser/finance

PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
NET=nobridge-finance_default

echo "=== adding Invoice-Management columns (if not exists) ==="
docker run --rm -i --network "$NET" postgres:17 psql -v ON_ERROR_STOP=1 "$LOCAL" <<'SQL'
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "suggestedType"      TEXT;
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "suggestedFrequency" TEXT;
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "approvedFrequency"  TEXT;
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "paymentStatus"      TEXT NOT NULL DEFAULT 'unpaid';
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "dueDate"            TIMESTAMP(3);
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "paidAt"             TIMESTAMP(3);
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "invoiceNumber"      TEXT;
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "paymentMethod"      TEXT;
ALTER TABLE "CostSubmission" ADD COLUMN IF NOT EXISTS "paymentNote"        TEXT;

-- Legacy reconciliation: items approved under the OLD flow were already booked
-- (createSingleEntry ran at approval). Mark them paid so the new "Mark paid"
-- action never double-books them. Safe + idempotent (only touches already-booked
-- approved rows that haven't been stamped yet).
UPDATE "CostSubmission"
   SET "paymentStatus" = 'paid',
       "paidAt"        = COALESCE("reviewedAt", "updatedAt")
 WHERE "status" = 'approved'
   AND "createdEntryId" IS NOT NULL
   AND "paidAt" IS NULL;
SQL

echo "=== verify columns ==="
docker run --rm -i --network "$NET" postgres:17 psql "$LOCAL" \
  -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'CostSubmission' ORDER BY ordinal_position;"

echo "=== done — Invoice-Management columns ready ==="
