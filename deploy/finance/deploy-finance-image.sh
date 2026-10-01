#!/usr/bin/env bash
# Loads a freshly-built finance image (tar.gz already scp'd to ~/finance/) and
# recreates ONLY the app container. finance-db is untouched.
#
# Since 2026-10-01 the image is built with basePath /finance (served at
# app.nobridge.co/finance), so every in-container URL carries that prefix.
set -u
cd /home/azureuser/finance
BASE=/finance
docker load -i finance-image.tar.gz
docker compose -f docker-compose.finance.yml up -d --force-recreate finance
sleep 6
echo "--- verify ---"
printf 'dashboard API : '; curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:3100${BASE}/api/dashboard?period=overall"
printf 'health        : '; curl -s "http://127.0.0.1:3100${BASE}/api/health"; echo
# Cloud MCP connector: read the live agent token from the DB and do an MCP
# `initialize` handshake against the app. 200 = route mounted, token accepted,
# tools reachable. Token is read at runtime, never stored in this script.
TOKEN=$(docker exec nobridge-finance-db psql -U finance -d finance -tAc "SELECT \"agentApiToken\" FROM \"AppSettings\" WHERE id='singleton';" 2>/dev/null | tr -d '[:space:]')
if [ -n "$TOKEN" ]; then
  printf 'mcp connector : '; curl -s -o /dev/null -w '%{http_code}\n' -X POST "http://127.0.0.1:3100${BASE}/mcp/$TOKEN" \
    -H 'Content-Type: application/json' \
    --data-raw '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'
else
  echo 'mcp connector : (no agent token set; skipped)'
fi
printf 'running       : '; docker ps --filter name=nobridge-finance --format '{{.Names}}={{.Status}}' | tr '\n' ' '; echo
rm -f finance-image.tar.gz
