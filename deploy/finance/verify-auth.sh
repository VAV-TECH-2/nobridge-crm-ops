#!/usr/bin/env bash
# READ-ONLY: probes the Finance app's own auth via localhost:3100 (bypasses Caddy)
# to confirm fail-closed behavior BEFORE removing the Caddy basic-auth gate.
# No writes (public submit is probed with GET so no rows are created).
B="${1:-http://127.0.0.1:3100}"
echo "base: $B"
probe() { printf '  %-48s -> %s\n' "$2" "$(curl -s -o /dev/null -w '%{http_code}' "$B$1")"; }
echo "== pages (no session) =="
probe "/finance"                                "/finance bare     (expect 307/308 ->login)"
probe "/finance/"                               "/finance/         (expect 308)"
probe "/finance/login"                          "/login            (expect 200)"
probe "/finance/submit"                         "/submit  public   (expect 200)"
probe "/finance/cost-submission"                "/cost-submission  (expect 307 ->login)"
echo "== APIs (no session, expect 401) =="
probe "/finance/api/dashboard?period=overall"   "dashboard      (full)"
probe "/finance/api/categories?type=expense"    "categories     (member)"
probe "/finance/api/settings/exchange-rate"     "exchange-rate  (member GET)"
probe "/finance/api/submissions?status=pending" "submissions    (full)"
echo "== public / auth (NOT gated) =="
probe "/finance/api/auth/me"                    "auth/me        (expect 200)"
probe "/finance/api/public/submit"              "public submit GET (expect 405, NOT 401)"
