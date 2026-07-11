#!/usr/bin/env bash
set -u
cd /home/azureuser/finance
DB=$(grep '^DATABASE_URL=' .env.finance | cut -d= -f2- | tr -d '"')
echo "=== server version ==="
docker run --rm postgres:16 psql "$DB" -t -A -c "show server_version;"
echo "=== row counts (baseline, n_live_tup) ==="
docker run --rm postgres:16 psql "$DB" -t -A -F'|' -c "select relname, n_live_tup from pg_stat_user_tables order by relname;"
echo "=== exact counts (key tables) ==="
docker run --rm postgres:16 psql "$DB" -t -A -F'|' -c "select 'RecurringCost', count(*) from \"RecurringCost\" union all select 'OneTimeCost', count(*) from \"OneTimeCost\" union all select 'Income', count(*) from \"Income\" union all select 'Category', count(*) from \"Category\" union all select 'AmountChange', count(*) from \"AmountChange\" union all select 'FixedFutureIncome', count(*) from \"FixedFutureIncome\";"
