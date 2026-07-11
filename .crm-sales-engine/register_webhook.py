"""Register the Twenty -> engine webhook (opportunity create/update) via the metadata API."""
import json, tw

TARGET = "http://nobridge-sales-engine:8080/webhooks/twenty"
mut = "mutation C($input: CreateWebhookInput!){ createWebhook(input:$input){ id targetUrl operations } }"
data = {"targetUrl": TARGET,
        "operations": ["opportunity.created", "opportunity.updated"],
        "description": "Nobridge Sales Engine"}
st, r = tw.meta(mut, {"input": data})
print("CREATE:", st, json.dumps(r)[:600])
