#!/usr/bin/env python3
"""One-time seeder: load domains-seed.txt (from the Instantly email-accounts
export) into the MASTER workspace member's Twenty blocklist as '@domain'
entries. Runs from the workstation over SSH; idempotent (skips handles the
master already has, live or soft-deleted rows count as live only).

The guard service then mirrors these to every other workspace member and
sweeps matching companies/people. Day-to-day edits happen in the CRM UI
(Settings -> Accounts -> Blocklist as vilca@nobridge.co), not here.
"""
import os
import subprocess
import sys

VM = "azureuser@20.189.126.94"
SCHEMA = "workspace_4cukon3ltvwq3m1goqws3p4lv"
MASTER = "3a7817ce-f274-4a2c-b2eb-a43a9506a88f"  # vilca@nobridge.co
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "domains-seed.txt")


def vm_psql(sql):
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", VM,
         "sudo docker exec -i twenty-db-1 psql -U postgres -d default"
         " -q -v ON_ERROR_STOP=1 -tA -f -"],
        input=sql, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("psql failed: " + r.stderr[:800])
    return [ln for ln in r.stdout.split("\n") if ln != ""]


def q(s):
    return "'" + s.replace("'", "''") + "'"


def main():
    with open(SEED) as f:
        domains = sorted({ln.strip().lower() for ln in f if ln.strip()})
    handles = ["@" + d for d in domains]
    have = set(vm_psql(
        'SELECT lower(handle) FROM %s.blocklist '
        'WHERE "workspaceMemberId"=%s AND "deletedAt" IS NULL '
        'AND handle IS NOT NULL;' % (SCHEMA, q(MASTER))))
    missing = [h for h in handles if h not in have]
    print("seed domains: %d | master already has: %d | inserting: %d"
          % (len(handles), len(handles) - len(missing), len(missing)))
    if not missing:
        return
    vals = ",".join(
        "(%s,%s,'blocklist-guard-seed','IMPORT','blocklist-guard-seed','IMPORT')"
        % (q(h), q(MASTER)) for h in missing)
    vm_psql('INSERT INTO %s.blocklist '
            '(handle,"workspaceMemberId","createdByName","createdBySource",'
            '"updatedByName","updatedBySource") VALUES %s;' % (SCHEMA, vals))
    total = vm_psql('SELECT count(*) FROM %s.blocklist '
                    'WHERE "workspaceMemberId"=%s AND "deletedAt" IS NULL;'
                    % (SCHEMA, q(MASTER)))[0]
    print("done - master blocklist now has %s live entries" % total)


if __name__ == "__main__":
    sys.exit(main())
