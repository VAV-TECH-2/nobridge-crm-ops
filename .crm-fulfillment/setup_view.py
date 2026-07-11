"""Create the 'By Stage' KANBAN view on fulfillment (groups + card fields) and
surface the key new fields as columns on the existing 'All Fulfillments' table."""
import json, tw

FULFILLMENT = "14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"
TABLE_VIEW  = "08915153-2ce2-424b-acce-2fc0e4e70be0"
STAGE_FIELD = "27353cc8-c646-4e83-a7d5-528fd3ef4494"
STAGE_VALUES = ["REACHED_OUT", "TEASER", "NDA", "DUE_DILIGENCE_VDR", "WAITING_ON_OFFER"]

F = {  # field name -> metadata id
  "name":"1947e958-92d6-40de-bbed-f3083bdf17a1", "stage":STAGE_FIELD,
  "prospectType":"a308732f-b89b-45ec-8466-732ac288116c", "company":"25c6a661-9020-4589-b671-eb7eafd69eb0",
  "companyType":"0c39acb2-d4a1-4a4f-bb22-1bd7cc7b0ed1", "pointOfContact":"3061f206-0d94-4108-a5f0-492de7bb2ed4",
  "country":"01c54529-4611-4453-957c-ad0ef37bbd27", "engagementStatus":"d14c5689-0fcd-43a7-8044-c04b495a2a51",
  "outcome":"cf2681b7-0b69-4aad-b6e3-4355a4c23497", "nextSteps":"f3b36959-e37b-4f44-b6e5-b81b75ca1362",
  "lastContact":"56228d81-1d28-43a5-8da5-6e0609088038", "followUpDate":"<unused>", "mandate":"<unused>",
}

CREATE_VIEW  = "mutation($input:CreateViewInput!){ createView(input:$input){ id name type } }"
CREATE_VG    = "mutation($input:CreateViewGroupInput!){ createViewGroup(input:$input){ id fieldValue } }"
CREATE_VF    = "mutation($input:CreateViewFieldInput!){ createViewField(input:$input){ id } }"

def vf(view_id, field_id, pos, visible=True, size=150):
    st, r = tw.meta(CREATE_VF, {"input": {"viewId": view_id, "fieldMetadataId": field_id,
                                           "position": pos, "isVisible": visible, "size": size}})
    return st == 200 and r.get("data", {}).get("createViewField"), r

def main():
    # 1. KANBAN view
    st, r = tw.meta(CREATE_VIEW, {"input": {
        "name": "By Stage", "objectMetadataId": FULFILLMENT, "type": "KANBAN",
        "icon": "IconLayoutKanban", "position": 1, "mainGroupByFieldMetadataId": STAGE_FIELD}})
    if st != 200 or not r.get("data", {}).get("createView"):
        print("!! createView FAILED:", st, json.dumps(r)[:500]); return
    kanban = r["data"]["createView"]["id"]
    print("+ KANBAN view 'By Stage':", kanban)

    # 2. view groups (one per stage option)
    for i, val in enumerate(STAGE_VALUES):
        st, r = tw.meta(CREATE_VG, {"input": {"viewId": kanban, "fieldValue": val,
                                              "position": i, "isVisible": True}})
        print(("  + group " if r.get("data",{}).get("createViewGroup") else "  !! group FAIL "),
              val, "" if r.get("data",{}).get("createViewGroup") else json.dumps(r)[:200])

    # 3. card fields on the kanban (chips shown on cards)
    card = [("prospectType",0),("companyType",1),("company",2),("country",3),("lastContact",4),("engagementStatus",5)]
    for name, pos in card:
        ok, r = vf(kanban, F[name], pos)
        print(("  + card field " if ok else "  !! card FAIL "), name, "" if ok else json.dumps(r)[:200])

    # 4. surface key new fields as columns on the existing TABLE view (Float positions
    #    slot them right after `name` at 0, before createdAt at 1)
    print("=== table columns ===")
    table_cols = [("stage",0.10),("prospectType",0.20),("company",0.30),("companyType",0.40),
                  ("pointOfContact",0.50),("country",0.60),("engagementStatus",0.70),
                  ("outcome",0.80),("nextSteps",0.86),("lastContact",0.90)]
    for name, pos in table_cols:
        ok, r = vf(TABLE_VIEW, F[name], pos)
        print(("  + col " if ok else "  !! col FAIL "), name, "" if ok else json.dumps(r)[:200])
    print("=== DONE ===  kanban view id:", kanban)

if __name__ == "__main__":
    main()
