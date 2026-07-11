#!/usr/bin/env bash
# Dumps every read endpoint's full JSON to a file so pre/post-deploy can be diffed.
# Usage: snapshot-metrics.sh <label>   (writes ~/finance/metrics-<label>.txt)
set -u
LABEL="${1:-snap}"
OUT="/home/azureuser/finance/metrics-${LABEL}.txt"
B="http://127.0.0.1:3100/finance"
: > "$OUT"
for u in \
  "/api/dashboard?period=overall" \
  "/api/dashboard?period=this_week" \
  "/api/dashboard?period=this_month" \
  "/api/dashboard?period=this_quarter" \
  "/api/dashboard?period=this_year" \
  "/api/dashboard?period=forecast&months=3" \
  "/api/analysis" \
  "/api/analysis?live=true" ; do
  echo "### $u" >> "$OUT"
  code=$(curl -s -o /tmp/body -w '%{http_code}' "$B$u")
  echo "HTTP $code" >> "$OUT"
  cat /tmp/body >> "$OUT"
  echo >> "$OUT"
done
echo "wrote $OUT"
cat "$OUT"
