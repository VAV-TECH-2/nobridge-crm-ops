#!/usr/bin/env bash
# PHASE 1 (non-destructive): stand up the local Postgres and copy the public
# schema from Supabase into it. The app keeps running on Supabase throughout —
# no cutover here. Verify the printed counts match before running phase 2.
set -u
cd /home/azureuser/finance

# 1. DB password for compose substitution (~/finance/.env, default compose env file)
if ! grep -q '^FINANCE_DB_PASSWORD=' .env 2>/dev/null; then
  echo "FINANCE_DB_PASSWORD=$(openssl rand -hex 18)" >> .env
  echo "generated FINANCE_DB_PASSWORD"
fi
chmod 600 .env
PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)

# 2. Bring up ONLY the new Postgres (leaves the running app untouched)
docker compose -f docker-compose.finance.yml up -d finance-db

# 3. Wait until it accepts connections
echo -n "waiting for finance-db: "
for i in $(seq 1 40); do
  if docker exec nobridge-finance-db pg_isready -U finance -d finance >/dev/null 2>&1; then echo "ready"; break; fi
  sleep 2; echo -n "."
done

SUPA=$(grep '^DATABASE_URL=' .env.finance | cut -d= -f2- | tr -d '"')
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
NET=nobridge-finance_default

# 4. Dump ONLY the public schema (the app's tables) and load into finance-db.
#    --no-owner/--no-privileges strips Supabase roles. One container reaches both
#    Supabase (egress) and finance-db (compose network).
echo "=== migrating public schema (Supabase -> finance-db) ==="
docker run --rm --network "$NET" postgres:17 bash -c \
  "pg_dump --schema=public --no-owner --no-privileges '$SUPA' | psql -v ON_ERROR_STOP=0 '$LOCAL'" 2>&1 | tail -8

# 5. Exact count comparison on the app tables
CNT="select 'RecurringCost' t, count(*) n from \"RecurringCost\" \
 union all select 'OneTimeCost', count(*) from \"OneTimeCost\" \
 union all select 'Income', count(*) from \"Income\" \
 union all select 'Category', count(*) from \"Category\" \
 union all select 'AmountChange', count(*) from \"AmountChange\" \
 union all select 'RawEntry', count(*) from \"RawEntry\" \
 union all select 'Budget', count(*) from \"Budget\" \
 union all select 'FixedFutureIncome', count(*) from \"FixedFutureIncome\" \
 union all select 'AppSettings', count(*) from \"AppSettings\" order by t;"
echo "=== SOURCE (Supabase) ==="
docker run --rm postgres:17 psql "$SUPA" -t -A -F'|' -c "$CNT"
echo "=== DEST (finance-db) ==="
docker run --rm --network "$NET" postgres:17 psql "$LOCAL" -t -A -F'|' -c "$CNT"
echo "=== compare the two lists above; they must match before phase 2 ==="
