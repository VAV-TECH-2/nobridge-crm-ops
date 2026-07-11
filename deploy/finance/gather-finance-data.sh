#!/usr/bin/env bash
# READ-ONLY: dump raw rows + exercise GET endpoints to verify math empirically.
# (Skips /api/settings/exchange-rate — its GET can re-fetch + mutate the rate.)
cd /home/azureuser/finance
PW=$(grep '^FINANCE_DB_PASSWORD=' .env | cut -d= -f2-)
LOCAL="postgresql://finance:${PW}@finance-db:5432/finance"
Q(){ docker run --rm --network nobridge-finance_default postgres:17 psql "$LOCAL" -t -A -F'|' -c "$1"; }

echo "=== settings (rate|displayCur|budget|budgetCur|breakEven) ==="
Q 'select "exchangeRate","displayCurrency",budget,"budgetCurrency","breakEvenTarget" from "AppSettings";'
echo "=== income (amount|cur|date|isRecurring|freq|source) ==="
Q 'select amount,currency,date::date,"isRecurring",frequency,source from "Income" order by date;'
echo "=== recurring (amount|cur|freq|start|end|active|name) ==="
Q 'select amount,currency,frequency,"startDate"::date,"endDate"::date,"isActive",name from "RecurringCost" order by name;'
echo "=== onetime currency mix (cur|count|sum) ==="
Q 'select currency,count(*),round(sum(amount)::numeric,2) from "OneTimeCost" group by currency;'
echo "=== recurring currency mix ==="
Q 'select currency,count(*) from "RecurringCost" group by currency;'
echo "=== amountHistory vs startDate (name|start|first_rate|n_changes) -- first_rate>start = uncounted gap ==="
Q 'select rc.name, rc."startDate"::date, min(ac."effectiveDate")::date, count(ac.*) from "RecurringCost" rc left join "AmountChange" ac on ac."recurringCostId"=rc.id group by rc.id, rc.name, rc."startDate" order by rc.name;'
echo "=== onetime date span (min|max|count) ==="
Q 'select min(date)::date, max(date)::date, count(*) from "OneTimeCost";'

B='http://127.0.0.1:3100/finance'
echo; echo "=== functional GET probes (HTTP code  url) ==="
for u in "/api/dashboard?period=overall" "/api/dashboard?period=this_month" "/api/dashboard?period=this_year" "/api/dashboard?period=this_week" "/api/dashboard?period=this_quarter" "/api/dashboard?period=forecast&months=3" "/api/analysis" "/api/analysis?live=true" "/api/entries?type=recurring" "/api/entries?type=onetime" "/api/entries?type=income" "/api/fixed-future-income" "/api/categories" "/api/settings/budget" "/api/settings/ai-key"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$B$u")
  echo "  $code  $u"
done
echo; echo "=== dashboard overall (key fields) ==="; curl -s "$B/api/dashboard?period=overall"; echo
echo; echo "=== dashboard forecast 3mo (key fields) ==="; curl -s "$B/api/dashboard?period=forecast&months=3"; echo
echo; echo "=== analysis (snippet) ==="; curl -s "$B/api/analysis" | head -c 700; echo
