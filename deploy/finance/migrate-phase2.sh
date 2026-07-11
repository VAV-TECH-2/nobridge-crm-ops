#!/usr/bin/env bash
# PHASE 2 (cutover): repoint the app from Supabase to the local finance-db and
# recreate it. Keeps a .env.finance.supabase.bak so we can revert to Supabase
# instantly if anything looks wrong.
set -u
cd /home/azureuser/finance
PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"

cp .env.finance .env.finance.supabase.bak
echo "backed up .env.finance -> .env.finance.supabase.bak"

# Repoint both URLs to the local DB ( | delimiter since the URL contains / )
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=\"${LOCAL}\"|" .env.finance
sed -i "s|^DIRECT_URL=.*|DIRECT_URL=\"${LOCAL}\"|"   .env.finance
echo "--- new DB target in .env.finance (masked) ---"
grep -E '^DATABASE_URL=|^DIRECT_URL=' .env.finance | sed -E 's#(://[^:]+:)[^@]+@#\1<PW>@#'

# Recreate the app container so it loads the new env + depends_on finance-db
docker compose -f docker-compose.finance.yml up -d
sleep 6

echo "--- container now points at (masked) ---"
docker exec nobridge-finance sh -c 'printenv DATABASE_URL' | sed -E 's#(://[^:]+:)[^@]+@#\1<PW>@#'
echo "--- verify (HTTP) ---"
printf 'dashboard API : '; curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:3100/finance/api/dashboard?period=overall'
printf 'entries API   : '; curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:3100/finance/api/entries?type=recurring'
echo "--- dashboard data snippet (proves real data from local DB) ---"
curl -s 'http://127.0.0.1:3100/finance/api/dashboard?period=overall' | head -c 300; echo
echo "--- finance logs (tail) ---"
docker logs --tail 10 nobridge-finance
