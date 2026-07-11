#!/usr/bin/env bash
# Creates the ExchangeRate table on finance-db AHEAD of deploying the new image,
# and seeds ONE snapshot at epoch from the current AppSettings.exchangeRate.
#
# Why first: the new code's loadRates() runs `prisma.exchangeRate.findMany()`. If
# the table is absent that query THROWS (relation does not exist), crashing every
# dashboard/analysis endpoint. The currently-running (old) app never touches this
# table, so creating it now is invisible to it — zero risk to the live app.
#
# Why seed at epoch with the current rate: rateOn(date) returns the latest
# snapshot with effectiveDate <= date, falling back to the EARLIEST snapshot for
# anything older. A single epoch snapshot therefore makes point-in-time
# conversion collapse to today's flat rate => post-deploy numbers reproduce
# pre-deploy numbers EXACTLY. That is our regression check.
#
# Idempotent: IF NOT EXISTS on table/index; ON CONFLICT DO NOTHING on the seed.
set -u
cd /home/azureuser/finance
PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
NET=nobridge-finance_default
Q(){ docker run --rm --network "$NET" postgres:17 psql "$LOCAL" "$@"; }

echo "=== current AppSettings.exchangeRate (will seed this exact value) ==="
Q -t -A -c 'select "exchangeRate" from "AppSettings" where id='"'"'singleton'"'"';'

echo "=== create table + index (Prisma-compatible DDL) ==="
Q -c 'CREATE TABLE IF NOT EXISTS "ExchangeRate" (
  "id" TEXT NOT NULL,
  "usdToIdr" DOUBLE PRECISION NOT NULL,
  "effectiveDate" TIMESTAMP(3) NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "ExchangeRate_pkey" PRIMARY KEY ("id")
);'
Q -c 'CREATE INDEX IF NOT EXISTS "ExchangeRate_effectiveDate_idx" ON "ExchangeRate"("effectiveDate");'

echo "=== seed one epoch snapshot from current settings rate ==="
Q -c 'INSERT INTO "ExchangeRate" ("id","usdToIdr","effectiveDate","createdAt")
  SELECT '"'"'seed-initial-rate'"'"', "exchangeRate", '"'"'1970-01-01 00:00:00'"'"', CURRENT_TIMESTAMP
  FROM "AppSettings" WHERE id='"'"'singleton'"'"'
  ON CONFLICT ("id") DO NOTHING;'

echo "=== verify: columns ==="
Q -t -A -F'|' -c "select column_name,data_type from information_schema.columns where table_name='ExchangeRate' order by ordinal_position;"
echo "=== verify: seeded rows (id|usdToIdr|effectiveDate) ==="
Q -t -A -F'|' -c 'select id,"usdToIdr","effectiveDate" from "ExchangeRate" order by "effectiveDate";'
echo "=== verify: snapshot == settings rate? (expect t) ==="
Q -t -A -c 'select (select "usdToIdr" from "ExchangeRate" order by "effectiveDate" limit 1) = (select "exchangeRate" from "AppSettings" where id='"'"'singleton'"'"') as matches;'
