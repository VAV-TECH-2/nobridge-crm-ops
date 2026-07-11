#!/usr/bin/env python3
"""Register (or update) an automation in the External Workflows registry.

Append one manifest entry; the next registry sync (<=5 min) surfaces it in the CRM
'External Workflows' menu automatically. This is the documented "edits go through
Claude" entry point. Run on the VM (where /opt/heydeal-automation-registry lives).

Usage:
  register_automation.py --key noreply-nudge --name "7-Day No-Reply Nudge" \\
      --unit noreply-nudge --script /opt/heydeal-noreply-nudge/nudge.py \\
      --schedule "Daily 00:00 UTC" --description "Flags prospects with no reply in 7 days."

`--unit` is the systemd unit base name (without .timer/.service). Re-running with an
existing --key updates that entry in place (and preserves its recordId).
"""
import os, json, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "registry.json")


def main():
    ap = argparse.ArgumentParser(description="Register an automation in External Workflows")
    ap.add_argument("--key", required=True, help="stable unique key for this automation")
    ap.add_argument("--name", required=True, help="display name shown in the CRM")
    ap.add_argument("--unit", required=True, help="systemd unit base name (no .timer/.service)")
    ap.add_argument("--script", required=True, help="absolute path to the script on the VM")
    ap.add_argument("--schedule", default="", help="human schedule, e.g. 'Daily 00:00 UTC'")
    ap.add_argument("--description", default="", help="plain-English 'what it does'")
    a = ap.parse_args()

    reg = json.load(open(REGISTRY)) if os.path.isfile(REGISTRY) else []
    prev = next((e for e in reg if e["key"] == a.key), None)
    entry = {"key": a.key, "name": a.name, "unit": a.unit, "scriptPath": a.script,
             "schedule": a.schedule, "description": a.description,
             "recordId": prev.get("recordId") if prev else None}
    if prev:
        reg[reg.index(prev)] = entry
        print("updated entry:", a.key)
    else:
        reg.append(entry)
        print("added entry:", a.key)
    json.dump(reg, open(REGISTRY, "w"), indent=1)
    print("registry now has %d automation(s). Next sync will reflect it within 5 min." % len(reg))


if __name__ == "__main__":
    main()
