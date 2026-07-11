"""Bring the fulfillment views to spec:
- TABLE: hide Created by / Last update / Updated by; add Notes + Days Since Contact columns.
- Record-page FIELDS_WIDGET: hide Created by / Last update / Updated by (keep Creation date).
- KANBAN 'By Stage': reorder groups to the 7-stage order; hide the empty group.

Idempotent. python fix_views.py --apply   (default: dry run)
"""
import json, sys, tw
APPLY = "--apply" in sys.argv

TABLE  = "08915153-2ce2-424b-acce-2fc0e4e70be0"
WIDGET = "35554471-d537-44d3-8a52-edb18d554700"
KANBAN = "3aad7c27-2757-4db1-9ba0-dd44df299c6e"

NOTES = "ae0765ac-2c41-49a0-bf4e-dcaa84ffda0d"
DAYS  = "76df38f1-c124-4979-bee6-d65e0fdd6712"

# viewField ids of the columns to hide (createdBy/updatedAt/updatedBy)
HIDE = {
    TABLE:  ["08d86823-2939-43da-b33f-50e651ffb517",   # createdBy
             "f22ea074-d51e-4d91-a5f6-9431aa7350ed",   # updatedAt (Last update)
             "1bfbc517-32f6-48c3-8913-a87f35efd85e"],  # updatedBy
    WIDGET: ["08ca43e4-89b4-48de-9f23-4af36b311df3",   # createdBy
             "42022bbb-2b2e-40ee-9455-9033e6a754d5",   # updatedAt
             "14a43fcb-ca42-44b3-852f-beff50931a04"],  # updatedBy
}

# KANBAN group order (stage value -> position); empty group hidden
GROUP_ORDER = {"REACHED_OUT":0, "MEETING_1":1, "NDA":2, "MEETING_2":3,
               "DUE_DILIGENCE_VDR":4, "MEETING_3":5, "WAITING_ON_OFFER":6}

U_VF = "mutation U($input:UpdateViewFieldInput!){ updateViewField(input:$input){ id isVisible } }"
C_VF = "mutation C($input:CreateViewFieldInput!){ createViewField(input:$input){ id } }"
U_VG = "mutation U($input:UpdateViewGroupInput!){ updateViewGroup(input:$input){ id position isVisible } }"


def hide(vfid):
    if not APPLY: print("   would hide", vfid); return
    st, r = tw.meta(U_VF, {"input": {"id": vfid, "update": {"isVisible": False}}})
    print(("   hid " if st == 200 and r.get("data", {}).get("updateViewField") else "   !! FAIL hide ") + vfid,
          "" if st == 200 else json.dumps(r)[:200])


def add_col(view, fid, pos):
    if not APPLY: print("   would add col", fid, "pos", pos); return
    st, r = tw.meta(C_VF, {"input": {"viewId": view, "fieldMetadataId": fid,
                                     "position": pos, "isVisible": True, "size": 150}})
    print(("   + col " if st == 200 and r.get("data", {}).get("createViewField") else "   !! FAIL col "), fid,
          "" if st == 200 else json.dumps(r)[:200])


def existing_table_cols():
    st, r = tw.meta("""query($v:String!){ getViewFields(viewId:$v){ fieldMetadataId } }""", {"v": TABLE})
    return {x["fieldMetadataId"] for x in (r.get("data", {}).get("getViewFields") or [])}


def main():
    print("MODE:", "APPLY" if APPLY else "DRY RUN")

    print("\n# TABLE — hide audit columns")
    for vfid in HIDE[TABLE]:
        hide(vfid)
    print("# TABLE — add Notes + Days Since Contact")
    have = existing_table_cols()
    if NOTES not in have: add_col(TABLE, NOTES, 0.91)
    else: print("   notes col exists")
    if DAYS not in have: add_col(TABLE, DAYS, 0.92)
    else: print("   daysSinceContact col exists")

    print("\n# RECORD-PAGE WIDGET — hide audit fields")
    for vfid in HIDE[WIDGET]:
        hide(vfid)

    print("\n# KANBAN — reorder groups + hide empty")
    st, r = tw.meta("""query($v:String){ getViewGroups(viewId:$v){ id fieldValue position isVisible } }""", {"v": KANBAN})
    for g in r.get("data", {}).get("getViewGroups") or []:
        val = g["fieldValue"]
        if val in GROUP_ORDER:
            target = GROUP_ORDER[val]
            if g["position"] != target or not g["isVisible"]:
                if APPLY:
                    st2, r2 = tw.meta(U_VG, {"input": {"id": g["id"], "update": {"position": target, "isVisible": True}}})
                    print(f"   {val} -> pos {target}", "ok" if st2 == 200 else json.dumps(r2)[:150])
                else:
                    print(f"   would move {val} -> pos {target}")
        else:  # empty / stale group
            if APPLY:
                st2, r2 = tw.meta(U_VG, {"input": {"id": g["id"], "update": {"isVisible": False}}})
                print(f"   hide stale group '{val}'", "ok" if st2 == 200 else json.dumps(r2)[:150])
            else:
                print(f"   would hide stale group '{val}'")

    print("\nDONE." if APPLY else "\nDRY RUN. Re-run with --apply.")


if __name__ == "__main__":
    main()
