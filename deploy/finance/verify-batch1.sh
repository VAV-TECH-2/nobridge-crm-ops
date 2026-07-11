#!/usr/bin/env bash
B='http://127.0.0.1:3100/finance'
echo "=== dashboard overall (expect runway ~= budgetRunway 3.25, not null) ==="
curl -s "$B/api/dashboard?period=overall"; echo
echo
echo "=== analysis BASE projections (expect recurring-only income; no $521 phantom) ==="
curl -s "$B/api/analysis" | head -c 380; echo
echo
echo "=== analysis LIVE projections (recurring income + fixed-future buckets) ==="
curl -s "$B/api/analysis?live=true" | head -c 380; echo
echo
echo "=== endpoints still 200? ==="
for u in "/api/dashboard?period=this_month" "/api/entries?type=recurring" "/api/fixed-future-income"; do
  printf '  %s  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$B$u")" "$u"
done
