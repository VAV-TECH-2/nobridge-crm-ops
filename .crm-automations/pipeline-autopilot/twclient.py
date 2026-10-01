"""Twenty transport for the pipeline autopilot — auth, throttling, REST/GraphQL/metadata.

Dual-mode on purpose, because this code runs in two places:

  ON THE VM (the live path)   token read from /home/azureuser/sales-engine/.env, requests to
                              http://127.0.0.1:3000. Same as .crm-automations/clienttype-sync/
                              sync.py:54-58 — the engine .env is the de-facto credential store for
                              everything on that box.
  ON A LAPTOP (dry runs)      token minted in-process from APP_SECRET, fetched over SSH so the
                              secret never lands on disk. Same as .crm-migrate-v2/tw.py:25-53.
                              Requests go to https://app.nobridge.co.

Mode is detected from the filesystem, not from an env var, so nothing has to be remembered. Set
AUTOPILOT_FORCE_REMOTE=1 to use the laptop path even on the VM (useful when comparing the two).

Throttle is 0.7s between requests (~85/min) against Twenty's 100-per-60s cap, with a sleep-and-
retry on 429. Do not lower it: the cap is per workspace, so this shares it with clienttype-sync
(every 2 min) and blocklist-guard (every 2 min).
"""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE_ID = "4997fc5b-3a7a-4b88-9af6-7e97cda53693"
API_KEY_ID = "c28fcffa-169a-46b5-9585-e2e209851b0f"   # "Look-Up Integration" -> Admin role
VM = "azureuser@20.189.126.94"
ENGINE_ENV = "/home/azureuser/sales-engine/.env"

REMOTE_HOST = "https://app.nobridge.co"
LOCAL_HOST = "http://127.0.0.1:3000"

# Twenty's own rate limit. 0.7s ~= 85 req/min against a 100/60s cap that is shared workspace-wide.
MIN_INTERVAL = float(os.environ.get("AUTOPILOT_THROTTLE", "0.7"))

_token = None
_last = [0.0]


def on_vm():
    """True when running on the CRM VM, where the engine .env is readable."""
    if os.environ.get("AUTOPILOT_FORCE_REMOTE") == "1":
        return False
    return os.path.exists(ENGINE_ENV)


def host():
    return LOCAL_HOST if on_vm() else REMOTE_HOST


def _env_value(key, path=ENGINE_ENV):
    """Read one KEY=value out of an .env file. Tolerates quotes and inline comments."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith(key + "="):
                continue
            val = line.split("=", 1)[1].strip()
            if val[:1] in ("'", '"') and val[-1:] == val[:1] and len(val) > 1:
                return val[1:-1]
            return val
    raise SystemExit("%s not found in %s" % (key, path))


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


def _mint():
    """A 1-hour API-key JWT on Twenty's legacy HS256 path (no `kid` header)."""
    app_secret = _app_secret()
    # legacy verify secret = sha256hex(APP_SECRET + workspaceId + "API_KEY"), used as the HMAC key
    secret = hashlib.sha256((app_secret + WORKSPACE_ID + "API_KEY").encode()).hexdigest()
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": WORKSPACE_ID, "type": "API_KEY", "workspaceId": WORKSPACE_ID,
               "jti": API_KEY_ID, "iat": now, "exp": now + 3600}
    si = (_b64(json.dumps(header, separators=(",", ":")).encode()) + b"."
          + _b64(json.dumps(payload, separators=(",", ":")).encode()))
    sig = hmac.new(secret.encode(), si, hashlib.sha256).digest()
    return (si + b"." + _b64(sig)).decode()


def token():
    global _token
    if _token:
        return _token
    _token = _env_value("TWENTY_API_KEY") if on_vm() else _mint()
    return _token


def _req(url, body=None, method="GET"):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(5):
        dt = time.time() - _last[0]
        if dt < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - dt)
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _last[0] = time.time()
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            payload = e.read().decode()[:1500]
            # 429 means the 60s window is spent; waiting it out is the only cure.
            if e.code == 429 and attempt < 4:
                time.sleep(61)
                continue
            return e.code, {"_error": payload}
        except Exception as e:  # noqa: BLE001 - transport errors are data here, not exceptions
            _last[0] = time.time()
            if attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            return 0, {"_error": repr(e)}
    return 0, {"_error": "exhausted retries"}


def rest(method, path, body=None):
    return _req(host() + "/rest" + path, body, method)


def gql(query, variables=None, metadata=False):
    ep = "/metadata" if metadata else "/graphql"
    st, r = _req(host() + ep, {"query": query, "variables": variables or {}}, "POST")
    return st, r


def meta(query, variables=None):
    return gql(query, variables, metadata=True)


def gql_checked(query, variables=None, metadata=False):
    """GraphQL that raises on transport or GraphQL-level errors. Returns the `data` payload."""
    st, r = gql(query, variables, metadata)
    if st != 200 or r.get("errors") or "_error" in r:
        raise RuntimeError("graphql %s: %s" % (st, json.dumps(r)[:600]))
    return r["data"]


if __name__ == "__main__":
    print("mode:", "VM (engine .env)" if on_vm() else "remote (minted)", "| host:", host())
    st, r = rest("GET", "/fulfillments?limit=1")
    print("REST /fulfillments:", st, json.dumps(r)[:160])
    st, r = meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }')
    if st == 200 and "data" in r:
        objs = {n["node"]["nameSingular"]: n["node"]["id"] for n in r["data"]["objects"]["edges"]}
        print("METADATA objects:", len(objs))
        for k in ("buyOpportunity", "sellOpportunity", "otherOpportunity", "fulfillment",
                  "networking"):
            print("   %-18s %s" % (k, objs.get(k)))
    else:
        print("METADATA:", st, json.dumps(r)[:300])
