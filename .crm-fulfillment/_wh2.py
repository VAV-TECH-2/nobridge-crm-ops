import json, tw
for label, fn, q in [
  ("CORE webhooks", tw.gql, "query{ webhooks{ edges{ node{ id targetUrl operations } } } }"),
  ("METADATA getWebhooks", tw.meta, "query{ getWebhooks{ id targetUrl operations } }"),
  ("METADATA webhooks", tw.meta, "query{ webhooks{ edges{ node{ id targetUrl operations } } } }"),
]:
    st, r = fn(q)
    if r.get("data"):
        print(f"{label}: OK", json.dumps(r["data"])[:800]); 
    else:
        errs=[e.get("message") for e in r.get("errors",[])]
        print(f"{label}: {st} errs={errs[:1]}")
