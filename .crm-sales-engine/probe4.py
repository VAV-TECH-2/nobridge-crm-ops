import json, tw
st, r = tw.meta('query{ __type(name:"Mutation"){ fields{ name args{ name type{ kind name ofType{ kind name ofType{ kind name } } } } } } }')
for f in r["data"]["__type"]["fields"]:
    if f["name"] == "createWebhook":
        print("createWebhook ARGS:", json.dumps(f["args"]))
for tn in ["CreateWebhookInput", "WebhookCreateInput", "CreateOneWebhookInput", "WebhookInput", "CreateWebhookData"]:
    st, r = tw.meta('query{ __type(name:"%s"){ name inputFields{ name type{ kind name ofType{ kind name } } } } }' % tn)
    t = r.get("data", {}).get("__type")
    if t:
        print(tn, "INPUTFIELDS:", json.dumps([(x["name"]) for x in t["inputFields"]]))
st, r = tw.meta('query{ webhooks{ edges{ node{ id targetUrl operations } } } }')
print("EXISTING:", st, json.dumps(r)[:400])
