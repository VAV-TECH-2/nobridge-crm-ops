"""Delete the no-op internal-URL webhook (SSRF-blocked); reconciler is the live path."""
import json, tw
WID = "ac0cbf8e-615c-4514-813d-ec24a9243b0a"
st, r = tw.meta('query{ __type(name:"Mutation"){ fields{ name args{ name type{ kind name ofType{ kind name } } } } } }')
for f in r["data"]["__type"]["fields"]:
    if f["name"] == "deleteWebhook":
        print("deleteWebhook args:", json.dumps(f["args"]))
for q, v in [
    ("mutation D($input: DeleteWebhookInput!){ deleteWebhook(input:$input){ id } }", {"input": {"id": WID}}),
    ("mutation D($id: UUID!){ deleteWebhook(id:$id){ id } }", {"id": WID}),
]:
    st, r = tw.meta(q, v)
    print("try:", st, json.dumps(r)[:200])
    if st == 200 and r.get("data", {}).get("deleteWebhook"):
        print("DELETED OK")
        break
