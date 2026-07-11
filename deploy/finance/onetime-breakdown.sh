#!/usr/bin/env bash
set -u
cd /home/azureuser/finance
PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
NET=nobridge-finance_default
Q(){ docker run --rm --network "$NET" postgres:17 psql "$LOCAL" -t -A -F'|' -c "$1"; }
echo "=== one-time COSTS by category (name|usd_total@16800) ==="
Q 'select coalesce(c.name,'"'"'(none)'"'"'), round(sum(case when o.currency='"'"'IDR'"'"' then o.amount/16800.0 else o.amount end)::numeric,4)
   from "OneTimeCost" o left join "Category" c on c.id=o."categoryId" group by c.name order by 2 desc;'
echo "=== one-time INCOME by source (source|usd_total@16800) ==="
Q 'select source, round(sum(case when currency='"'"'IDR'"'"' then amount/16800.0 else amount end)::numeric,4)
   from "Income" where "isRecurring"=false group by source order by 2 desc;'
echo "=== recurring INCOME (source|amount|cur|freq) ==="
Q 'select source,amount,currency,frequency from "Income" where "isRecurring"=true;'
