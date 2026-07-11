#!/usr/bin/env python3
"""External Workflows registry sync.

Mirrors every registered automation (a systemd timer + its script) into the
read-only 'External Workflows' custom object in Twenty, so each automation's live
status / code / schedule / last run / last result are visible in the CRM UI.

Design:
- Source of truth is the VM: systemd unit state + the script file + registry.json.
- Records are written via the Twenty core GraphQL API. The mirror fields are
  isUIReadOnly (blocked in the browser) but remain API-writable — that's why the
  UI shows them read-only while this sync can still update them.
- Self-healing: a deleted record is recreated; a manual rename/edit is overwritten
  on the next run. The VM stays the single source of truth.

Runs as root from systemd (automation-registry-sync.service) every 5 minutes.
Stdlib only.
"""
import os, sys, json, time, hmac, hashlib, base64, subprocess
import urllib.request, urllib.error
from datetime import datetime, timezone

HERE        = os.path.dirname(os.path.abspath(__file__))
REGISTRY    = os.path.join(HERE, "registry.json")
RESULT_FILE = os.path.join(HERE, "last_result.txt")

WORKSPACE_ID = "4997fc5b-3a7a-4b88-9af6-7e97cda53693"
API_KEY_ID   = "c28fcffa-169a-46b5-9585-e2e209851b0f"   # "Look-Up Integration" -> Admin role
GQL_URL      = "http://127.0.0.1:3000/graphql"
CODE_CAP     = 8000   # max chars of a script mirrored into the Code field


# ----- token: HS256 legacy API-key JWT, minted fresh from APP_SECRET each run -----
def app_secret():
    out = subprocess.run(["docker", "exec", "twenty-server-1", "printenv", "APP_SECRET"],
                         capture_output=True, text=True, timeout=60)
    s = out.stdout.strip()
    if not s:
        raise RuntimeError("could not read APP_SECRET: " + out.stderr[:300])
    return s


def _b64(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=")


def mint_token():
    secret = hashlib.sha256((app_secret() + WORKSPACE_ID + "API_KEY").encode()).hexdigest()
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": WORKSPACE_ID, "type": "API_KEY", "workspaceId": WORKSPACE_ID,
               "jti": API_KEY_ID, "iat": now, "exp": now + 3600}
    si = _b64(json.dumps(header, separators=(",", ":")).encode()) + b"." + \
         _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), si, hashlib.sha256).digest()
    return (si + b"." + _b64(sig)).decode()


_TOKEN = None
def gql(query, variables=None):
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = mint_token()
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(GQL_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + _TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


# ----- systemd introspection -----
def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def sd_show(unit, prop):
    return run(["systemctl", "show", unit, "--property=" + prop, "--value"]).stdout.strip()


def to_iso(systemd_ts):
    """Convert a systemd human timestamp (e.g. 'Mon 2026-06-15 17:45:32 UTC') to ISO-8601 UTC."""
    if not systemd_ts or systemd_ts in ("n/a", "0"):
        return None
    iso = run(["date", "-u", "-d", systemd_ts, "+%Y-%m-%dT%H:%M:%S.000Z"]).stdout.strip()
    return iso or None


def unit_status(unit):
    """(status, last_run_iso) for an automation whose units are <unit>.timer / <unit>.service."""
    timer, svc = unit + ".timer", unit + ".service"
    enabled = run(["systemctl", "is-enabled", timer]).stdout.strip()
    active  = run(["systemctl", "is-active", timer]).stdout.strip()
    exists  = bool(enabled) or sd_show(svc, "LoadState") == "loaded"
    result  = sd_show(svc, "Result")
    exit_c  = sd_show(svc, "ExecMainStatus")
    last_run = to_iso(sd_show(svc, "ExecMainStartTimestamp") or sd_show(timer, "LastTriggerUSec"))
    if not exists:
        return "DISABLED", last_run
    if (result and result != "success") or (exit_c and exit_c != "0"):
        return "ERROR", last_run
    if enabled in ("enabled", "enabled-runtime") and active == "active":
        return "ACTIVE", last_run
    return "PAUSED", last_run


def container_status(name):
    """(status, last_run_iso) for a docker-container automation (continuous service)."""
    running = run(["docker", "inspect", "-f", "{{.State.Running}}", name]).stdout.strip()
    if running != "true":
        st = run(["docker", "inspect", "-f", "{{.State.Status}}", name]).stdout.strip()
        return ("ERROR" if st in ("exited", "dead", "restarting") else "DISABLED"), None
    started = run(["docker", "inspect", "-f", "{{.State.StartedAt}}", name]).stdout.strip()
    return "ACTIVE", to_iso(started)


def container_last_result(name):
    out = run(["docker", "logs", "--tail", "8", name])
    lines = [l for l in (out.stdout + out.stderr).splitlines() if l.strip()]
    tail = lines[-1] if lines else "(no recent log)"
    return ("Running continuously; reconciles the CRM every 5 min. Last log line: " + tail)[:600]


def last_result(entry):
    """Prefer the automation's own last_result.txt; fall back to its last journal line."""
    rf = os.path.join(os.path.dirname(entry["scriptPath"]), "last_result.txt")
    if os.path.isfile(rf):
        try:
            txt = open(rf).read().strip()
            if txt:
                return txt[:600]
        except Exception:
            pass
    out = run(["journalctl", "-u", entry["unit"] + ".service", "-n", "1", "--no-pager", "-o", "cat"])
    return (out.stdout.strip() or "(no output yet)")[:600]


def read_code(path):
    try:
        txt = open(path).read()
    except Exception as e:
        return "(could not read %s: %r)" % (path, e)
    if len(txt) > CODE_CAP:
        txt = txt[:CODE_CAP] + "\n\n... (truncated -- full script on the VM at %s)" % path
    return txt


# ----- record upsert (custom object: externalWorkflow) -----
QUERY = ("query($after:String){ externalWorkflows(first:200, after:$after){ "
         "pageInfo{ hasNextPage endCursor } edges{ node{ id name } } } }")

_DATA = ("name:$name, status:$status, description:$description, schedule:$schedule, "
         "code:$code, lastResult:$lastResult, systemdUnit:$systemdUnit, "
         "scriptPath:$scriptPath, lastRunAt:$lastRunAt")
_VARS = ("$name:String,$status:String,$description:String,$schedule:String,$code:String,"
         "$lastResult:String,$systemdUnit:String,$scriptPath:String,$lastRunAt:DateTime")
CREATE = "mutation(%s){ createExternalWorkflow(data:{%s}){ id } }" % (_VARS, _DATA)
UPDATE = "mutation($id:UUID!,%s){ updateExternalWorkflow(id:$id, data:{%s}){ id } }" % (_VARS, _DATA)


def list_records():
    by_name, ids, after = {}, set(), None
    while True:
        d = gql(QUERY, {"after": after})
        if "errors" in d:
            raise RuntimeError("list query errors: " + json.dumps(d["errors"])[:400])
        c = d["data"]["externalWorkflows"]
        for e in c["edges"]:
            by_name[e["node"]["name"]] = e["node"]["id"]
            ids.add(e["node"]["id"])
        if c["pageInfo"]["hasNextPage"]:
            after = c["pageInfo"]["endCursor"]
        else:
            return by_name, ids


def main():
    reg = json.load(open(REGISTRY))
    by_name, ids = list_records()
    synced = errors = 0
    for entry in reg:
        if entry.get("container"):
            status, last_run = container_status(entry["container"])
            result = container_last_result(entry["container"])
            unit_field = "docker: " + entry["container"]
        else:
            status, last_run = unit_status(entry["unit"])
            result = last_result(entry)
            unit_field = entry["unit"]
        data = {
            "name": entry["name"], "status": status,
            "description": entry.get("description", ""), "schedule": entry.get("schedule", ""),
            "code": read_code(entry["scriptPath"]), "lastResult": result,
            "systemdUnit": unit_field, "scriptPath": entry["scriptPath"], "lastRunAt": last_run,
        }
        rid = entry.get("recordId")
        if rid not in ids:                  # cached id gone (deleted) -> adopt same-name or recreate
            rid = by_name.get(entry["name"])
        try:
            if rid:
                d = gql(UPDATE, dict(data, id=rid))
            else:
                d = gql(CREATE, data)
            if "errors" in d:
                raise RuntimeError(json.dumps(d["errors"])[:300])
            if not rid:
                rid = d["data"]["createExternalWorkflow"]["id"]
            entry["recordId"] = rid
            synced += 1
        except Exception as ex:
            errors += 1
            print("upsert-failed %s: %s" % (entry.get("key"), ex))
    json.dump(reg, open(REGISTRY, "w"), indent=1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    msg = "OK -- synced %d automation(s) at %s UTC" % (synced, now)
    if errors:
        msg = "%d error(s); synced %d at %s UTC" % (errors, synced, now)
    open(RESULT_FILE, "w").write(msg + "\n")
    print(msg)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
