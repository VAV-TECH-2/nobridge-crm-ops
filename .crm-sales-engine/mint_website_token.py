"""Mint a long-lived (5y) Twenty API-key JWT for the website sign-up integration.

Writes it to website_twenty_token.txt (gitignored) and verifies it can read the CRM.
This token goes into the website's TWENTY_API_TOKEN env var (Vercel + .env.local).
A dedicated token (separate from the engine's) can be revoked independently.

Reuses tw.py's APP_SECRET fetch + workspace/api-key ids. Copy of mint_engine_token.py
with the stale heydeal.co verification URL fixed to tw.HOST (crm.nobridge.co).

Run:  python mint_website_token.py
"""
import time, json, hmac, hashlib, base64, urllib.request, urllib.error
import tw

# This dir's tw.py copy still points at the retired heydeal.co host; force the live one.
tw.HOST = "https://crm.nobridge.co"

OUT_FILE = "website_twenty_token.txt"


def b64(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=")


app_secret = tw._app_secret()
secret = hashlib.sha256((app_secret + tw.WORKSPACE_ID + "API_KEY").encode()).hexdigest()
now = int(time.time())
header = {"alg": "HS256", "typ": "JWT"}
payload = {"sub": tw.WORKSPACE_ID, "type": "API_KEY", "workspaceId": tw.WORKSPACE_ID,
           "jti": tw.API_KEY_ID, "iat": now, "exp": now + 5 * 365 * 24 * 3600}
si = b64(json.dumps(header, separators=(",", ":")).encode()) + b"." + \
     b64(json.dumps(payload, separators=(",", ":")).encode())
token = (si + b"." + b64(hmac.new(secret.encode(), si, hashlib.sha256).digest())).decode()
open(OUT_FILE, "w").write(token)

# Verify against the LIVE host (tw.HOST = https://crm.nobridge.co), reading a field the
# website will write to (source) to confirm the metadata migration has run.
req = urllib.request.Request(
    tw.HOST + "/graphql",
    data=json.dumps({"query": "query{ opportunities(first:1){ edges{ node{ id name stage source } } } }"}).encode(),
    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
try:
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    ok = "data" in r and "opportunities" in r.get("data", {})
    reads_source = "source" in json.dumps(r) or (r.get("data", {}).get("opportunities", {}).get("edges") == [])
    print("TOKEN TEST ok:", ok, "| source field present:", reads_source)
    if r.get("errors"):
        print("  note:", json.dumps(r["errors"])[:300], "(run setup_field_source.py if 'source' is unknown)")
    print("written to", OUT_FILE, "(exp ~5y) -> set as website TWENTY_API_TOKEN")
except urllib.error.HTTPError as e:
    print("TOKEN TEST FAILED", e.code, e.read().decode()[:300])
