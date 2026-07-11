"""Shared helpers for the Fulfillment build/import.

Mints a Twenty API-key JWT (HS256 legacy path) from APP_SECRET, which is fetched
in-process over SSH so the secret never lands on disk or in logs. Exposes thin
REST / core-GraphQL / metadata-GraphQL clients.
"""
import os, json, time, hmac, hashlib, base64, subprocess, urllib.request, urllib.error, sys

sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE_ID = "4997fc5b-3a7a-4b88-9af6-7e97cda53693"
API_KEY_ID   = "c28fcffa-169a-46b5-9585-e2e209851b0f"   # "Look-Up Integration" -> Admin role
HOST         = "https://crm.nobridge.co"
VM           = "azureuser@20.189.126.94"

# Live object/workspace ids (filled in as discovered; keep here for reuse)
FULFILLMENT_OBJECT_ID = "f1857c46-93a0-4f0c-9f0e-PLACEHOLDER"  # resolved at runtime via metadata

_token = None

def _app_secret():
    out = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", VM,
         "sudo docker exec twenty-server-1 printenv APP_SECRET"],
        capture_output=True, text=True, timeout=60)
    s = out.stdout.strip()
    if not s:
        raise RuntimeError("could not read APP_SECRET: " + out.stderr[:300])
    return s

def _b64(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=")

def token():
    global _token
    if _token:
        return _token
    app_secret = _app_secret()
    # legacy verify secret = sha256hex(APP_SECRET + workspaceId + "API_KEY"), used as HMAC key
    secret = hashlib.sha256((app_secret + WORKSPACE_ID + "API_KEY").encode()).hexdigest()
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}            # no kid -> legacy HS256 path
    payload = {"sub": WORKSPACE_ID, "type": "API_KEY", "workspaceId": WORKSPACE_ID,
               "jti": API_KEY_ID, "iat": now, "exp": now + 3600}
    si = _b64(json.dumps(header, separators=(",", ":")).encode()) + b"." + \
         _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), si, hashlib.sha256).digest()
    _token = (si + b"." + _b64(sig)).decode()
    return _token

_last = [0.0]
MIN_INTERVAL = 0.7   # ~85 req/min, under Twenty's 100/60s cap

def _req(url, body=None, method="GET"):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(5):
        dt = time.time() - _last[0]
        if dt < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - dt)
        req = urllib.request.Request(url, data=data, method=method,
            headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _last[0] = time.time()
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code == 429 and attempt < 4:   # rate-limit window exhausted: wait it out
                time.sleep(61)
                continue
            return e.code, {"_error": e.read().decode()[:1500]}
        except Exception as e:
            _last[0] = time.time()
            return 0, {"_error": repr(e)}

def rest(method, path, body=None):
    return _req(HOST + "/rest" + path, body, method)

def gql(query, variables=None, metadata=False):
    ep = "/metadata" if metadata else "/graphql"
    return _req(HOST + ep, {"query": query, "variables": variables or {}}, "POST")

def meta(query, variables=None):
    return gql(query, variables, metadata=True)

if __name__ == "__main__":
    # smoke test: confirm the token authenticates against all three endpoints
    st, r = rest("GET", "/fulfillments?limit=1")
    print("REST /fulfillments:", st, json.dumps(r)[:200])
    st, r = meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }')
    if st == 200 and "data" in r:
        objs = {n["node"]["nameSingular"]: n["node"]["id"]
                for n in r["data"]["objects"]["edges"]}
        print("METADATA objects:", len(objs), "| fulfillment id =", objs.get("fulfillment"),
              "| opportunity id =", objs.get("opportunity"), "| company id =", objs.get("company"),
              "| person id =", objs.get("person"))
    else:
        print("METADATA:", st, json.dumps(r)[:400])
