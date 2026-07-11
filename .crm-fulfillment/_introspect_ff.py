import json, tw
FULFILLMENT = "14cded1b-affb-4d3d-bbe3-2c07f4ea47fc"
q = """query($id:UUID!){ object(id:$id){ id nameSingular labelSingular
  fieldsList{ id name label type isActive isCustom
    options }
}}"""
st, r = tw.meta(q, {"id": FULFILLMENT})
if st != 200 or not r.get("data",{}).get("object"):
    print("ERR", st, json.dumps(r)[:800]); raise SystemExit
obj = r["data"]["object"]
print("OBJECT", obj["nameSingular"], obj["labelSingular"])
for f in sorted(obj["fieldsList"], key=lambda x: x["name"]):
    line = f"- {f['name']} | label={f['label']} | type={f['type']} | active={f['isActive']} | custom={f['isCustom']} | id={f['id']}"
    print(line)
    if f.get("options"):
        for o in f["options"]:
            print(f"      opt: value={o.get('value')} label={o.get('label')} color={o.get('color')} pos={o.get('position')} id={o.get('id')}")
