"""Mint a long-lived (5y) Twenty API-key JWT for the engine, write to file, verify it works.
Reuses tw.py's APP_SECRET fetch + workspace/api-key ids."""
import time, json, hmac, hashlib, base64, urllib.request, urllib.error
import tw

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
open("engine_twenty_token.txt", "w").write(token)

req = urllib.request.Request(
    "https://heydeal.co/graphql",
    data=json.dumps({"query": "query{ opportunities(first:1){ edges{ node{ id name stage meetingOutcome } } } }"}).encode(),
    headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
try:
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    ok = bool(r.get("data", {}).get("opportunities"))
    print("TOKEN TEST ok:", ok, "| reads new field meetingOutcome:", "meetingOutcome" in json.dumps(r))
    print("written to engine_twenty_token.txt (exp ~5y)")
except urllib.error.HTTPError as e:
    print("TOKEN TEST FAILED", e.code, e.read().decode()[:300])
