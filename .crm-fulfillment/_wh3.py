import json, tw
st, r = tw.meta("query{ webhooks{ id targetUrl operations secret } }")
print("status", st)
print(json.dumps(r.get("data") or r, indent=1)[:1500])
