#!/usr/bin/env python3
import json
p = "/opt/heydeal-automation-registry/registry.json"
reg = json.load(open(p))
keys = {e.get("key") for e in reg}
if "blocklist-guard" not in keys:
    reg.append({
        "key": "blocklist-guard",
        "name": "Blocklist Guard",
        "unit": "blocklist-guard",
        "scriptPath": "/opt/heydeal-blocklist-guard/guard.py",
        "schedule": "Every 2 minutes",
        "description": "Enforces the cold-email sending-domain blocklist. The admin's CRM blocklist (Settings > Accounts > Blocklist, vilca@nobridge.co) is the master list; this mirrors it to every workspace member and soft-deletes any Company/Person auto-created from a blocked @domain (skips records attached to real deals/notes). Deleted ids logged to swept.json.",
        "recordId": None,
    })
    json.dump(reg, open(p, "w"), indent=1)
    print("added blocklist-guard")
else:
    print("blocklist-guard already present")
