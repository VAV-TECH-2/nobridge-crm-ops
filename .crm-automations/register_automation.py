#!/usr/bin/env python3
"""Register (or update) an automation so it appears on the ops dashboard's System tab.

Run this on the VM, where the live registry lives at
/opt/heydeal-automation-registry/registry.json. The dashboard reads that file on every
request, so a new entry shows up on the next page load — no restart, no sync job.

Each entry needs exactly one health probe, because that is how the dashboard decides
whether a card is green:

  --unit NAME        a systemd unit base name, no .timer/.service suffix. Works for both
                     timer-driven jobs and always-on services.
  --container NAME   a Docker container name, for anything running inside compose.
  --watch GLOB       for crontab jobs, which have neither. Health is judged by the output
                     the job produces: --watch is a glob of the files it writes, and the
                     newest match must be under --max-age-hours old and at least
                     --min-bytes big. This is the only honest signal for a cron job —
                     "the script exists" tells you nothing about whether it ran.

Examples:
  register_automation.py --key crm-draft-cleanup --name "Gmail Draft Cleanup" \\
      --unit crm-draft-cleanup --script /opt/crm-draft-cleanup/cleanup_draft_messages.py \\
      --schedule "Hourly" --description "Removes phantom sent emails from draft autosaves."

  register_automation.py --key nobridge-finance --name "Nobridge Finance" \\
      --container nobridge-finance --schedule "Always on" \\
      --description "The finance app at fin.nobridge.co."

  register_automation.py --key twenty-backup --name "CRM Database Backup" \\
      --watch '/var/backups/twenty/db-*.sql.gz' --max-age-hours 30 --min-bytes 1000000 \\
      --script /usr/local/bin/twenty-backup.sh --schedule "Nightly 03:15" \\
      --description "The only backup of the entire CRM database."

Re-running with an existing --key updates that entry in place and preserves its recordId,
so this is safe to run repeatedly.

After registering, add a matching entry to the dashboard's automation_docs.py under the
same --key. Without one the card appears but its "How it works" tab says there is no
documentation yet, which is the drift this registry has suffered from before.
"""
import argparse
import json
import os
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VM_REGISTRY = "/opt/heydeal-automation-registry/registry.json"
# On the VM the live registry wins. Off the VM this falls back to the copy in the repo,
# which is a mirror for reference — editing it there changes nothing until it is deployed.
REGISTRY = VM_REGISTRY if os.path.isfile(VM_REGISTRY) else os.path.join(HERE, "registry.json")


def main():
    ap = argparse.ArgumentParser(
        description="Register an automation on the ops dashboard's System tab")
    ap.add_argument("--key", required=True, help="stable unique key; must match automation_docs.py")
    ap.add_argument("--name", required=True, help="display name shown on the card")
    ap.add_argument("--unit", help="systemd unit base name (no .timer/.service)")
    ap.add_argument("--container", help="Docker container name")
    ap.add_argument("--watch", help="glob of output files, for crontab jobs")
    ap.add_argument("--max-age-hours", type=float, default=30,
                    help="with --watch: newest output older than this is unhealthy")
    ap.add_argument("--min-bytes", type=int, default=0,
                    help="with --watch: newest output smaller than this is unhealthy")
    ap.add_argument("--script", default="", help="absolute path to the source on the VM")
    ap.add_argument("--schedule", default="", help="human schedule, e.g. 'Nightly 03:15'")
    ap.add_argument("--description", default="", help="plain-English 'what it does'")
    a = ap.parse_args()

    probes = [p for p in (a.unit, a.container, a.watch) if p]
    if len(probes) != 1:
        ap.error("give exactly one of --unit, --container or --watch — that is the health probe")

    reg = json.load(open(REGISTRY)) if os.path.isfile(REGISTRY) else []
    prev = next((e for e in reg if e.get("key") == a.key), None)

    entry = {"key": a.key, "name": a.name, "scriptPath": a.script,
             "schedule": a.schedule, "description": a.description,
             "recordId": prev.get("recordId") if prev else None}
    if a.unit:
        entry["unit"] = a.unit
    elif a.container:
        entry["container"] = a.container
    else:
        entry["watchPath"] = a.watch
        entry["maxAgeHours"] = a.max_age_hours
        if a.min_bytes:
            entry["minBytes"] = a.min_bytes

    if os.path.isfile(REGISTRY):
        shutil.copy2(REGISTRY, REGISTRY + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    if prev:
        reg[reg.index(prev)] = entry
        print("updated entry:", a.key)
    else:
        reg.append(entry)
        print("added entry:", a.key)
    json.dump(reg, open(REGISTRY, "w"), indent=2)
    print("%s now has %d automation(s); the System tab reflects it on next page load."
          % (REGISTRY, len(reg)))


if __name__ == "__main__":
    main()
