"""Append the Sales Engine (Docker container) to the live External Workflows registry. Run on the VM."""
import json
p = "/opt/heydeal-automation-registry/registry.json"
reg = json.load(open(p))
if not any(e.get("key") == "sales-engine" for e in reg):
    reg.append({
        "key": "sales-engine",
        "name": "Nobridge Sales Engine",
        "container": "nobridge-sales-engine",
        "scriptPath": "/home/azureuser/sales-engine/src/index.ts",
        "schedule": "Continuous (reconciles the CRM every 5 min; reminders fire 09:00-18:00 Jakarta)",
        "description": "Buy-side sales automation. Watches buy-side opportunities and, as they move through the pipeline, creates Google Tasks and fires timed reminders / overdue escalations into the Sales Engine Google Chat space. Also runs follow-up chases, no-show rebooking, and 90-day re-engage, and detects calendar bookings + email replies. Reads the CRM every 5 minutes. Runs as a standalone Docker container on the VM (it is NOT a Twenty workflow).",
        "recordId": None,
    })
    json.dump(reg, open(p, "w"), indent=1)
    print("added sales-engine; keys:", [e["key"] for e in reg])
else:
    print("already present; keys:", [e["key"] for e in reg])
