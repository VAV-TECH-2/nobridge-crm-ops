import json, tw
st, r = tw.rest("GET", "/webhooks")
print("status", st)
# r may be a list or {data:{webhooks:[...]}}
hooks = r if isinstance(r, list) else (r.get("data",{}) or {}).get("webhooks", r)
print(json.dumps(hooks, indent=1)[:2000])
