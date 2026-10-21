"""Create the 'Sales Fulfillment' board under Others: same data points as Fulfillments,
copied live from the fulfillment object's metadata, with its own 4-stage pipeline.

Idempotent: skips the object, any field, view, view field, group or menu item that
already exists. Dry-run by default; pass --apply to write.
    python3 .crm-fulfillment/sales_fulfillment_setup.py [--apply]
"""
import sys, uuid, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tw

APPLY = "--apply" in sys.argv

SRC = "fulfillment"
NEW = dict(nameSingular="salesFulfillment", namePlural="salesFulfillments",
           labelSingular="Sales Fulfillment", labelPlural="Sales Fulfillments",
           icon="IconBriefcase", isLabelSyncedWithName=False,
           description="Sales fulfillment pipeline: same data points as Fulfillments, own stages")
OTHERS_FOLDER = "deed51fc-1afa-46b4-86d0-bb12cc58a620"   # sidebar folder 'Others'
MENU_POSITION = -0.75                                     # after Fulfillments (-1), before Network (-0.5)

STAGES = [("New Positive", "NEW_POSITIVE", "gray"), ("Responded", "RESPONDED", "blue"),
          ("Meeting Booked", "MEETING_BOOKED", "purple"),
          ("Share Back to Client", "SHARE_BACK_TO_CLIENT", "green")]

# inverse relation labels on Company / Person / Workspace Member
INVERSE = {"company": "Sales Fulfillments", "pointOfContact": "Sales Fulfillments (POC)",
           "owner": "Owned Sales Fulfillments"}
AUTO = {"timelineActivities", "attachments", "noteTargets", "taskTargets"}

OBJS = 'query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }'
FIELDS = ('query($id:UUID!){ object(id:$id){ fieldsList{ id name label type icon isCustom isSystem '
          'description options settings relation{ type targetObjectMetadata{ id nameSingular } '
          'targetFieldMetadata{ name icon } } } } }')
VIEWS = ('query($id:String!){ getViews(objectMetadataId:$id){ id name type key icon position '
         'mainGroupByFieldMetadataId viewFields{ fieldMetadataId position isVisible size } '
         'viewGroups{ fieldValue isVisible position } } }')
CREATE_OBJ = "mutation($input:CreateOneObjectInput!){ createOneObject(input:$input){ id } }"
CREATE_FLD = "mutation($input:CreateOneFieldMetadataInput!){ createOneField(input:$input){ id name } }"
CREATE_VIEW = "mutation($input:CreateViewInput!){ createView(input:$input){ id } }"
CREATE_VF = "mutation($input:CreateViewFieldInput!){ createViewField(input:$input){ id } }"
UPDATE_VF = "mutation($input:UpdateViewFieldInput!){ updateViewField(input:$input){ id } }"
CREATE_VG = "mutation($input:CreateViewGroupInput!){ createViewGroup(input:$input){ id } }"
NAV = 'query{ navigationMenuItems{ id targetObjectMetadataId folderId position } }'
CREATE_NAV = "mutation($input:CreateNavigationMenuItemInput!){ createNavigationMenuItem(input:$input){ id } }"
UPDATE_NAV = "mutation($input:UpdateOneNavigationMenuItemInput!){ updateNavigationMenuItem(input:$input){ id } }"


def ok(st, r, key):
    if st == 200 and (r.get("data") or {}).get(key):
        return r["data"][key]
    raise SystemExit("!! %s failed: %s %s" % (key, st, json.dumps(r)[:600]))


def object_ids():
    st, r = tw.meta(OBJS)
    return {e["node"]["nameSingular"]: e["node"]["id"] for e in ok(st, r, "objects")["edges"]}


def fields(oid):
    st, r = tw.meta(FIELDS, {"id": oid})
    return ok(st, r, "object")["fieldsList"]


def views(oid):
    st, r = tw.meta(VIEWS, {"id": oid})
    return ok(st, r, "getViews")


def do(label, query, variables, key):
    if not APPLY:
        print("  WOULD", label)
        return None
    st, r = tw.meta(query, variables)
    res = ok(st, r, key)
    print("  +", label)
    return res


def field_payload(oid, f, objs):
    p = {"objectMetadataId": oid, "name": f["name"], "label": f["label"], "type": f["type"],
         "icon": f["icon"], "description": f["description"] or None, "isLabelSyncedWithName": False}
    if f["name"] == "stage":
        p["options"] = [{"id": str(uuid.uuid4()), "label": l, "value": v, "color": c, "position": i}
                        for i, (l, v, c) in enumerate(STAGES)]
    elif f["options"]:
        p["options"] = [{"id": str(uuid.uuid4()), "label": o["label"], "value": o["value"],
                         "color": o["color"], "position": o["position"]} for o in f["options"]]
    if f["type"] == "RELATION":
        rel = f["relation"]
        p["relationCreationPayload"] = {"type": rel["type"],
            "targetObjectMetadataId": rel["targetObjectMetadata"]["id"],
            "targetFieldLabel": INVERSE[f["name"]],
            "targetFieldIcon": rel["targetFieldMetadata"]["icon"] or "IconBriefcase"}
        p["settings"] = f["settings"]
        p["description"] = "Sales Fulfillments tied to the " + {
            "company": "Company", "pointOfContact": "Person", "owner": "Workspace Member"}[f["name"]]
    return {k: v for k, v in p.items() if v is not None}


def main():
    print("MODE:", "APPLY" if APPLY else "DRY RUN")
    objs = object_ids()
    src = objs[SRC]
    oid = objs.get(NEW["nameSingular"])
    if oid:
        print("object exists:", oid)
    else:
        res = do("object Sales Fulfillment", CREATE_OBJ, {"input": {"object": NEW}}, "createOneObject")
        oid = res and res["id"]

    print("=== fields ===")
    src_fields = [f for f in fields(src) if f["isCustom"] and not f["isSystem"] and f["name"] not in AUTO]
    have = {f["name"] for f in fields(oid)} if oid else set()
    for f in src_fields:
        if f["name"] in have:
            print("  skip (exists)", f["name"])
            continue
        do("field %-18s %s" % (f["name"], f["type"]), CREATE_FLD,
           {"input": {"field": field_payload(oid, f, objs)}}, "createOneField")
    if not oid:
        print("dry run stops here (views need the object id)")
        return

    # map source field ids -> new field ids by name
    src_by_id = {f["id"]: f["name"] for f in fields(src)}
    new_by_name = {f["name"]: f["id"] for f in fields(oid)}

    print("=== views ===")
    new_views = {v["key"] or v["name"]: v for v in views(oid)}
    for sv in views(src):
        if sv["type"] not in ("TABLE", "KANBAN"):
            continue          # record-page FIELDS_WIDGET view is created with the object's page layout
        k = sv["key"] or sv["name"]
        nv = new_views.get(k)
        if not nv:
            inp = {"name": sv["name"], "objectMetadataId": oid, "type": sv["type"], "icon": sv["icon"],
                   "position": sv["position"], "visibility": "WORKSPACE", "openRecordIn": "SIDE_PANEL"}
            if sv["mainGroupByFieldMetadataId"]:
                inp["mainGroupByFieldMetadataId"] = new_by_name[src_by_id[sv["mainGroupByFieldMetadataId"]]]
            res = do("view " + sv["name"], CREATE_VIEW, {"input": inp}, "createView")
            if not res:
                continue
            nv = next(v for v in views(oid) if v["id"] == res["id"])
        existing = {vf["fieldMetadataId"]: vf for vf in nv["viewFields"]}
        for vf in sv["viewFields"]:
            fid = new_by_name.get(src_by_id.get(vf["fieldMetadataId"]))
            if not fid:
                continue
            want = {"position": vf["position"], "isVisible": vf["isVisible"], "size": vf["size"]}
            cur = existing.get(fid)
            if cur is None:
                tw.meta(CREATE_VF, {"input": dict(want, viewId=nv["id"], fieldMetadataId=fid)})
            elif any(cur[x] != want[x] for x in want):
                st, r = tw.meta('query($v:String!){ getViewFields(viewId:$v){ id fieldMetadataId } }', {"v": nv["id"]})
                vfid = next(x["id"] for x in r["data"]["getViewFields"] if x["fieldMetadataId"] == fid)
                tw.meta(UPDATE_VF, {"input": {"id": vfid, "update": want}})
        print("  view fields synced:", sv["name"])
        if sv["type"] == "KANBAN":
            have_groups = {g["fieldValue"] for g in nv["viewGroups"]}
            groups = [(v, True, i + 1) for i, (_, v, _) in enumerate(STAGES)] + [("", False, len(STAGES) + 1)]
            for val, vis, pos in groups:
                if val not in have_groups:
                    tw.meta(CREATE_VG, {"input": {"viewId": nv["id"], "fieldValue": val,
                                                  "isVisible": vis, "position": pos}})
            print("  kanban columns synced")

    print("=== sidebar ===")
    st, r = tw.meta(NAV)
    items = [i for i in ok(st, r, "navigationMenuItems") if i["targetObjectMetadataId"] == oid]
    if not items:
        do("menu item in Others", CREATE_NAV, {"input": {"type": "OBJECT", "targetObjectMetadataId": oid,
           "folderId": OTHERS_FOLDER, "position": MENU_POSITION}}, "createNavigationMenuItem")
    else:
        for i in items:
            if i["folderId"] != OTHERS_FOLDER or i["position"] != MENU_POSITION:
                do("move menu item into Others", UPDATE_NAV, {"input": {"id": i["id"], "update": {
                   "folderId": OTHERS_FOLDER, "position": MENU_POSITION}}}, "updateNavigationMenuItem")
            else:
                print("  menu item already in Others")
    print("DONE. object id:", oid)


if __name__ == "__main__":
    main()
