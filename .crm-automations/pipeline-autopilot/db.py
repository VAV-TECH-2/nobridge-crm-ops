"""Read-only Postgres access to the live Twenty database.

WHY SQL AND NOT THE API. Reads here are bulk and relational: "for each of 562 records, the last
inbound mail, the last outbound mail, the touch count since an anchor, and the next booked meeting".
That is one query in SQL and hundreds of paged REST calls otherwise. Writes are the opposite - they
go through the REST API (see crm.py) so Twenty's own business logic, timeline and search indexing
all fire. Same split as clienttype-sync (sync.py:64-74 reads by psql, writes by GraphQL).

READ-ONLY BY CONSTRUCTION. Every statement goes through psql in a transaction opened with
`SET TRANSACTION READ ONLY`, so a stray UPDATE in a query string fails rather than mutating
production. The autopilot has exactly one write path and it is not this file.

Dual-mode, like twclient: on the VM it runs `docker exec` directly; from a laptop it pipes the same
SQL over SSH. Both use stdin rather than -c, which avoids quote-escaping problems entirely - the
lesson recorded at .crm-automations/external_workflows_setup.py:53-61.
"""
import json
import os
import subprocess

SCHEMA = "workspace_4cukon3ltvwq3m1goqws3p4lv"
VM = "azureuser@20.189.126.94"
CONTAINER = "twenty-db-1"

# Path that only exists on the VM; the same probe twclient uses.
_VM_MARKER = "/home/azureuser/sales-engine/.env"


def on_vm():
    if os.environ.get("AUTOPILOT_FORCE_REMOTE") == "1":
        return False
    return os.path.exists(_VM_MARKER)


def _argv():
    inner = ["sudo", "docker", "exec", "-i", CONTAINER,
             "psql", "-U", "postgres", "-d", "default", "-v", "ON_ERROR_STOP=1", "-tAq", "-f", "-"]
    if on_vm():
        return inner
    return ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20", VM,
            " ".join(inner[:-3] + ["-tAq", "-f", "-"])]


def run(sql, timeout=180):
    """Execute SQL read-only and return raw stdout."""
    wrapped = "BEGIN;\nSET TRANSACTION READ ONLY;\n" + sql.rstrip().rstrip(";") + ";\nCOMMIT;\n"
    p = subprocess.run(_argv(), input=wrapped, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("psql failed: %s" % ((p.stderr or p.stdout)[:1500]))
    return p.stdout


def rows(inner_select, timeout=180):
    """Run a SELECT and return it as a list of dicts.

    The query is wrapped in json_agg so there is no delimiter parsing to get wrong - email subjects
    contain pipes, tabs and newlines, and a positional split on any of them eventually corrupts a
    record silently. Same trick as sync.py:72-74.
    """
    out = run("SELECT COALESCE(json_agg(t), '[]'::json) FROM (\n%s\n) t"
              % inner_select.rstrip().rstrip(";"), timeout=timeout).strip()
    if not out:
        return []
    # A wrapped statement echoes nothing else, but be defensive about stray blank lines.
    payload = "\n".join(ln for ln in out.splitlines() if ln.strip())
    return json.loads(payload)


def scalar(sql):
    out = run(sql).strip()
    return out.splitlines()[0] if out else None


if __name__ == "__main__":
    print("mode:", "VM" if on_vm() else "SSH")
    print("messages:", scalar('SELECT count(*) FROM "%s".message WHERE "deletedAt" IS NULL' % SCHEMA))
    r = rows('''
        SELECT o.id, o.name, o.stage::text AS stage
        FROM "%s"."_buyOpportunity" o
        WHERE o."deletedAt" IS NULL
        ORDER BY o.name
        LIMIT 3
    ''' % SCHEMA)
    for x in r:
        print("  ", x)
    # Prove the read-only guard actually bites.
    try:
        run('UPDATE "%s"."_buyOpportunity" SET "nextSteps" = \'nope\' WHERE false' % SCHEMA)
        print("READ-ONLY GUARD FAILED - an UPDATE was accepted")
    except RuntimeError as e:
        print("read-only guard: UPDATE rejected as expected")
