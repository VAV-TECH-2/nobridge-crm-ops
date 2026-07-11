#!/usr/bin/env bash
# Polls the Finance dashboard API until the (paused) Supabase DB is awake again.
# Exits 0 with DB_READY when /finance/api/dashboard returns 200; 1 on timeout.
url='http://127.0.0.1:3100/finance/api/dashboard?period=overall'
for i in $(seq 1 80); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$url")
  echo "poll $i: HTTP $code"
  if [ "$code" = "200" ]; then echo "DB_READY"; exit 0; fi
  sleep 15
done
echo "TIMEOUT"
exit 1
