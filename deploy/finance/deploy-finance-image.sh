#!/usr/bin/env bash
# Loads a freshly-built finance image (tar.gz already scp'd to ~/finance/) and
# recreates ONLY the app container. finance-db is untouched.
set -u
cd /home/azureuser/finance
docker load -i finance-image.tar.gz
docker compose -f docker-compose.finance.yml up -d --force-recreate finance
sleep 6
echo "--- verify ---"
printf 'dashboard API : '; curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:3100/api/dashboard?period=overall'
printf 'ai-key GET    : '; curl -s 'http://127.0.0.1:3100/api/settings/ai-key'; echo
printf 'running       : '; docker ps --filter name=nobridge-finance --format '{{.Names}}={{.Status}}' | tr '\n' ' '; echo
rm -f finance-image.tar.gz
