"""Create the 'External Workflows' custom object — a READ-ONLY visibility surface
for the custom automations (systemd timers) running on the VM.

Each record mirrors one automation: status / description / schedule / code snapshot /
last run / last result. Records are written by the registry-sync on the VM via API;
all fields are isUIReadOnly so they cannot be edited in the browser (API writes still
work — isUIReadOnly is a UI-only flag).

Idempotent: skips the object/fields/columns that already exist. Reuses tw.py
(token mint + metadata GraphQL) from the sibling .crm-fulfillment dir.
"""
import os, sys, json, uuid, subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".crm-fulfillment"))
import tw  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "external_workflows_meta.json")

CREATE_OBJ = "mutation($input:CreateOneObjectInput!){ createOneObject(input:$input){ id nameSingular } }"
CREATE_FLD = "mutation($input:CreateOneFieldMetadataInput!){ createOneField(input:$input){ id name } }"
UPDATE_FLD = "mutation($input:UpdateOneFieldMetadataInput!){ updateOneField(input:$input){ id name isUIReadOnly } }"
CREATE_VF  = "mutation($input:CreateViewFieldInput!){ createViewField(input:$input){ id } }"

STATUS_OPTS = [
    ("Active",   "ACTIVE",   "green"),
    ("Paused",   "PAUSED",   "yellow"),
    ("Error",    "ERROR",    "red"),
    ("Disabled", "DISABLED", "gray"),
]

# name, label, type, icon, options
FIELDS = [
    ("status",      "Status",       "SELECT",    "IconActivityHeartbeat", STATUS_OPTS),
    ("description", "What it does",  "TEXT",      "IconFileDescription",   None),
    ("schedule",    "Schedule",      "TEXT",      "IconClock",             None),
    ("code",        "Code",          "TEXT",      "IconCode",              None),
    ("lastRunAt",   "Last Run",      "DATE_TIME", "IconClockPlay",         None),
    ("lastResult",  "Last Result",   "TEXT",      "IconReportAnalytics",   None),
    ("systemdUnit", "Systemd Unit",  "TEXT",      "IconServerBolt",        None),
    ("scriptPath",  "Script Path",   "TEXT",      "IconFileCode",          None),
]

# Columns to surface on the default TABLE view, in order after `name` (position 0).
TABLE_COLS = [("status", 0.10), ("description", 0.15), ("schedule", 0.20),
              ("lastRunAt", 0.30), ("lastResult", 0.40)]


def opts(rows):
    return [{"id": str(uuid.uuid4()), "label": l, "value": v, "color": c, "position": i}
            for i, (l, v, c) in enumerate(rows)]


def vm_psql(sql):
    """Run a read-only query on the live Twenty DB via SSH and return stripped stdout.
    Avoids quote-escaping hell by piping the SQL to psql over stdin."""
    remote = "sudo docker exec -i twenty-db-1 psql -U postgres -d default -tA -f -"
    out = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", tw.VM, remote],
        input=sql, capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def get_object():
    st, r = tw.meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }')
    for e in r["data"]["objects"]["edges"]:
        if e["node"]["nameSingular"] == "externalWorkflow":
            oid = e["node"]["id"]
            # fieldsList is unpaginated (the fields{edges} connection truncates) -> reliable field map
            _, fr = tw.meta('query($id:UUID!){ object(id:$id){ fieldsList{ id name } } }', {"id": oid})
            fields = {f["name"]: f["id"] for f in fr["data"]["object"]["fieldsList"]}
            return oid, fields
    return None, {}


def create_field(obj, name, label, ftype, icon, options):
    f = {"objectMetadataId": obj, "name": name, "label": label, "type": ftype,
         "icon": icon, "isLabelSyncedWithName": False, "isUIReadOnly": True}
    if options:
        f["options"] = opts(options)
    st, r = tw.meta(CREATE_FLD, {"input": {"field": f}})
    node = r.get("data", {}).get("createOneField")
    print(("  + " if node else "  !! FAIL ") + name, "" if node else (str(st) + " " + json.dumps(r)[:300]))
    return node["id"] if node else None


def set_readonly(field_id, name):
    st, r = tw.meta(UPDATE_FLD, {"input": {"id": field_id, "update": {"isUIReadOnly": True}}})
    ok = r.get("data", {}).get("updateOneField")
    print(("  ~ read-only " if ok else "  !! ro FAIL ") + name, "" if ok else json.dumps(r)[:300])


def main():
    # 1. object (idempotent)
    oid, have = get_object()
    if oid:
        print("object 'externalWorkflow' already exists:", oid)
    else:
        st, r = tw.meta(CREATE_OBJ, {"input": {"object": {
            "nameSingular": "externalWorkflow", "namePlural": "externalWorkflows",
            "labelSingular": "External Workflow", "labelPlural": "External Workflows",
            "icon": "IconBolt", "isLabelSyncedWithName": False,
            "description": "Read-only mirror of custom automations running on the server. "
                           "Managed by Claude via the VM registry sync — edits here have no effect."}}})
        node = r.get("data", {}).get("createOneObject")
        if not node:
            print("!! createOneObject FAILED:", st, json.dumps(r)[:600]); return
        oid = node["id"]
        print("+ object 'External Workflows':", oid)
        _, have = get_object()

    # 2. fields (idempotent)
    print("=== fields ===")
    for name, label, ftype, icon, options in FIELDS:
        if name in have:
            print("  skip (exists)", name); continue
        create_field(oid, name, label, ftype, icon, options)

    # 3. lock the default `name` field read-only too (custom fields were created read-only)
    oid, have = get_object()
    print("=== read-only on name ===")
    if "name" in have:
        set_readonly(have["name"], "name")

    # 4. surface columns on the default TABLE view
    view_id = vm_psql("SELECT id FROM core.view WHERE \"objectMetadataId\"='%s' AND type='TABLE' "
                      "ORDER BY position LIMIT 1;" % oid)
    print("=== table columns (view %s) ===" % view_id)
    if view_id:
        for name, pos in TABLE_COLS:
            if name not in have:
                print("  !! missing field", name); continue
            st, r = tw.meta(CREATE_VF, {"input": {"viewId": view_id, "fieldMetadataId": have[name],
                                                  "position": pos, "isVisible": True, "size": 160}})
            ok = r.get("data", {}).get("createViewField")
            print(("  + col " if ok else "  !! col FAIL ") + name, "" if ok else json.dumps(r)[:200])
    else:
        print("  !! could not resolve default TABLE view id")

    json.dump({"object_id": oid, "fields": have, "view_id": view_id}, open(OUT, "w"), indent=1)
    print("DONE. meta ->", OUT)


if __name__ == "__main__":
    main()
