#!/usr/bin/env bash
# Post-deploy verification: CRM untouched + finance healthy + FX history intact.
set -u
cd /home/azureuser/finance
PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
NET=nobridge-finance_default

echo "===== CRM health (ABSOLUTE PRIORITY) ====="
echo -n "  healthz       : "; curl -s -o /dev/null -w '%{http_code}\n' https://crm.nobridge.co/healthz
echo -n "  / (CRM)       : "; curl -s -o /dev/null -w '%{http_code}\n' https://crm.nobridge.co/
echo -n "  /graphql      : "; curl -s -o /dev/null -w '%{http_code}\n' https://crm.nobridge.co/graphql
docker ps --format '{{.Names}} {{.Status}}' | grep twenty
echo "  -- twenty-server errors since deploy (last 10m) --"
docker logs twenty-server-1 --since 10m 2>&1 | grep -iE 'error|fatal|unhandled' | tail -5 || echo "  (none)"

echo; echo "===== Finance gate + endpoints ====="
echo -n "  /finance (no auth, 401): "; curl -s -o /dev/null -w '%{http_code}\n' https://fin.nobridge.co
echo -n "  /finance (auth,   200): "; curl -s -u "nobridge:${FINANCE_BASIC_AUTH_PW:-retired}" -o /dev/null -w '%{http_code}\n' https://fin.nobridge.co
B='http://127.0.0.1:3100/finance'
for u in "/api/dashboard?period=overall" "/api/dashboard?period=this_month" "/api/dashboard?period=this_year" "/api/dashboard?period=this_week" "/api/dashboard?period=this_quarter" "/api/dashboard?period=forecast&months=3" "/api/analysis" "/api/analysis?live=true" "/api/entries?type=recurring" "/api/entries?type=onetime" "/api/entries?type=income" "/api/fixed-future-income" "/api/categories" "/api/settings/budget" "/api/settings/ai-key" "/api/settings/exchange-rate"; do
  printf '  %s  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$B$u")" "$u"
done

echo; echo "===== FX history intact (expect ONE row: seed 16800 @ epoch) ====="
docker run --rm --network "$NET" postgres:17 psql "$LOCAL" -t -A -F'|' -c 'select count(*), min("usdToIdr"), max("usdToIdr") from "ExchangeRate";'
docker run --rm --network "$NET" postgres:17 psql "$LOCAL" -t -A -F'|' -c 'select id,"usdToIdr","effectiveDate" from "ExchangeRate" order by "effectiveDate";'

echo; echo "===== finance containers ====="
docker ps --filter name=nobridge-finance --format '{{.Names}} {{.Status}}'
echo "  -- finance app errors since deploy (last 10m) --"
docker logs nobridge-finance --since 10m 2>&1 | grep -iE 'error|fatal|unhandled|prisma' | tail -8 || echo "  (none)"
echo "===== END ====="
