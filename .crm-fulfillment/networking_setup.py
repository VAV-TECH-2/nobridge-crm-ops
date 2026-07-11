"""Create the 'Networking' custom object (menu item) for VC/PE relationship tracking:
lighter field model + 'By Stage' kanban. Idempotent-ish (skips object if it exists)."""
import uuid, json, tw

COMPANY = "825f8dff-2de8-4055-bb8a-a23f8c1cee20"
PERSON  = "6160d306-18a8-4d07-9772-4d29e62ca66f"

CREATE_OBJ = "mutation($input:CreateOneObjectInput!){ createOneObject(input:$input){ id nameSingular } }"
CREATE_FLD = "mutation($input:CreateOneFieldMetadataInput!){ createOneField(input:$input){ id name } }"
CREATE_VIEW= "mutation($input:CreateViewInput!){ createView(input:$input){ id } }"
CREATE_VF  = "mutation($input:CreateViewFieldInput!){ createViewField(input:$input){ id } }"

STAGES = [("Reached Out","REACHED_OUT","gray"),("Intro Call","INTRO_CALL","blue"),
          ("Ongoing Dialogue","ONGOING_DIALOGUE","purple"),("Actively Engaged","ACTIVELY_ENGAGED","green")]
ENGAGE = [("Not Contacted Yet","NOT_CONTACTED_YET","gray"),("In Discussions / Scheduled","IN_DISCUSSIONS_SCHEDULED","blue"),
          ("Awaiting Reply","AWAITING_REPLY","yellow"),("Held Off (Check Back In 3 Months)","HELD_OFF","orange"),
          ("Not Interested","NOT_INTERESTED","red"),("Crash Out (DNC)","CRASH_OUT_DNC","pink")]

def get_object():
    st,r = tw.meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular labelPlural fields{ edges{ node{ id name type } } } } } } }')
    for e in r["data"]["objects"]["edges"]:
        if e["node"]["nameSingular"] == "networking":
            return e["node"]["id"], {f["node"]["name"]: f["node"]["id"] for f in e["node"]["fields"]["edges"]}
    return None, {}

def opts(rows):
    return [{"id":str(uuid.uuid4()),"label":l,"value":v,"color":c,"position":i} for i,(l,v,c) in enumerate(rows)]

def field(obj, name, label, ftype, icon, options=None, rel=None):
    f = {"objectMetadataId":obj,"name":name,"label":label,"type":ftype,"icon":icon,"isLabelSyncedWithName":False}
    if options: f["options"] = options
    if rel: f["relationCreationPayload"] = rel
    st,r = tw.meta(CREATE_FLD, {"input":{"field":f}})
    ok = r.get("data",{}).get("createOneField")
    print(("  + " if ok else "  !! FAIL ")+name, "" if ok else (str(st)+" "+json.dumps(r)[:300]))

def main():
    oid,_ = get_object()
    if oid:
        print("object 'networking' already exists:", oid)
    else:
        st,r = tw.meta(CREATE_OBJ, {"input":{"object":{
            "nameSingular":"networking","namePlural":"networkings",
            "labelSingular":"Networking","labelPlural":"Networking",
            "icon":"IconAffiliate","isLabelSyncedWithName":False,
            "description":"VC / PE investor relationship tracking"}}})
        if not r.get("data",{}).get("createOneObject"):
            print("!! createOneObject FAILED:", st, json.dumps(r)[:500]); return
        oid = r["data"]["createOneObject"]["id"]
        print("+ object 'Networking':", oid)
    _, have = get_object()
    print("existing fields:", sorted(have))
    print("=== fields ===")
    specs = [("stage","Stage","SELECT","IconAffiliate",opts(STAGES),None),
             ("investorType","Investor Type","TEXT","IconCoin",None,None),
             ("country","Country","TEXT","IconWorld",None,None),
             ("engagementStatus","Engagement Status","SELECT","IconMessageDots",opts(ENGAGE),None),
             ("nextSteps","Next Steps","TEXT","IconArrowRight",None,None),
             ("lastContact","Last Contact","DATE","IconCalendar",None,None),
             ("followUpDate","Follow-up Date","DATE","IconCalendarDue",None,None),
             ("company","Company","RELATION","IconBuildingSkyscraper",None,
                {"type":"MANY_TO_ONE","targetObjectMetadataId":COMPANY,"targetFieldLabel":"Networking","targetFieldIcon":"IconAffiliate"}),
             ("pointOfContact","Point of Contact","RELATION","IconUserCircle",None,
                {"type":"MANY_TO_ONE","targetObjectMetadataId":PERSON,"targetFieldLabel":"Networking (POC)","targetFieldIcon":"IconAffiliate"})]
    for name,label,ftype,icon,o,rel in specs:
        if name in have: print("  skip (exists)", name); continue
        field(oid, name, label, ftype, icon, o, rel)

    # refresh ids, build kanban
    oid, have = get_object()
    print("=== kanban view ===")
    st,r = tw.meta(CREATE_VIEW, {"input":{"name":"By Stage","objectMetadataId":oid,"type":"KANBAN",
        "icon":"IconLayoutKanban","position":1,"mainGroupByFieldMetadataId":have["stage"]}})
    kanban = r.get("data",{}).get("createView",{}).get("id")
    print("  kanban:", kanban)
    if kanban:
        for i,n in enumerate(["investorType","company","country","lastContact","engagementStatus"]):
            tw.meta(CREATE_VF, {"input":{"viewId":kanban,"fieldMetadataId":have[n],"position":i,"isVisible":True,"size":150}})
        print("  + card fields added")
    # table view columns
    st,r = tw.meta('query($id:UUID!){ object(id:$id){ fieldsList{ id name } } }', {"id":oid})
    tv = None
    stv,rv = tw.meta('query{ objects(paging:{first:200}){ edges{ node{ id nameSingular } } } }')
    # find table view via DB-independent query
    print("DONE. object id:", oid, "| fields:", sorted(have))
    json.dump({"object_id":oid,"fields":have,"kanban":kanban},
              open(".crm-fulfillment/networking_meta.json","w"), indent=1)

if __name__ == "__main__":
    main()
