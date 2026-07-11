#!/usr/bin/env bash
# Swaps the new twenty-front overlay bundle into the live bind-mount and restarts
# only the server. Sanity-checks the new build first; the previous front-build is
# already backed up to ~/twenty/front-build.bak.* for rollback.
set -u
TARBALL=/home/azureuser/finance/front-build.tar.gz
STAGE=/home/azureuser/finance/front-build-new
DEST=/home/azureuser/twenty/front-build

rm -rf "$STAGE"; mkdir -p "$STAGE"
tar -xzf "$TARBALL" -C "$STAGE"

if [ ! -f "$STAGE/index.html" ] || ! grep -q twenty-env-config "$STAGE/index.html"; then
  echo "NEW_BUILD_INVALID — aborting; live front-build untouched"; exit 1
fi
echo "new build validated (index.html + env-config placeholder present)"

# Swap contents in place (keep the bind-mounted directory's inode).
rm -rf "${DEST:?}"/* "${DEST}"/.[!.]* 2>/dev/null || true
cp -a "$STAGE"/. "$DEST"/
echo "new front-build swapped in"

# Restart only the server; its entrypoint re-injects window._env_ (SERVER_URL)
# into the new index.html. Worker/db/redis stay up.
cd /home/azureuser/twenty && docker compose restart server
echo "server restarting; waiting for it to come back..."
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/)
  if [ "$code" = "200" ]; then echo "CRM_BACK after ~$((i*3))s"; break; fi
  sleep 3
done

echo '--- verify ---'
printf 'CRM local :3000   : '; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
printf 'CRM via Caddy     : '; curl -s -o /dev/null -w '%{http_code}\n' https://crm.nobridge.co/
printf 'env injected      : '; (grep -o 'REACT_APP_SERVER_BASE_URL[^,}"]*' "$DEST/index.html" | head -1) || echo 'NOT FOUND'
printf 'finance still up  : '; curl -s -u "nobridge:${FINANCE_BASIC_AUTH_PW:-retired}" -o /dev/null -w '%{http_code}\n' https://fin.nobridge.co
printf 'running           : '; docker ps --format '{{.Names}}' | tr '\n' ' '; echo
rm -f "$TARBALL"
