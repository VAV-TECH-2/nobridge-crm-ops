"""OpenAPI 3.1 rendered from the same tool registry MCP is rendered from.

A ChatGPT Custom GPT needs an OpenAPI document, not an MCP handshake. Rather than maintain a second
description of every tool — which is how the retired ops connector's stdio and cloud halves drifted
apart — this walks `tools.TOOLS` and emits one POST operation per tool. Add a tool to the registry
and both clients get it.

Four things ChatGPT specifically requires, all of which have bitten somebody:

  operationId must be unique and stable       it becomes the action name the model calls, so it is
                                              the tool name verbatim.
  a description on every operation            an action with none is offered to the model as a
                                              mystery and simply never gets called.
  no more than 30 operations                  we are well inside that; `selfcheck.py` asserts it so
                                              a future tool cannot quietly break the GPT.
  an absolute server URL                      a relative one makes the importer reject the document.

Auth is `Authorization: Bearer <token>` — the same tokens the MCP path takes in its URL, verified
against the same store, so revoking one revokes both.
"""
import deps  # noqa: F401
import tools

PUBLIC_BASE = "https://app.nobridge.co"

# ChatGPT refuses to import a document with more operations than this.
MAX_OPERATIONS = 30


def document():
    paths = {}
    for t in tools.TOOLS:
        schema = dict(t["input_schema"])
        # ChatGPT's importer is happier with an explicit (even empty) properties object.
        schema.setdefault("properties", {})
        summary = t["description"].strip().splitlines()[0].strip()
        paths["/ai/tools/" + t["name"]] = {
            "post": {
                "operationId": t["name"],
                "summary": summary[:300],
                "description": " ".join(t["description"].split()),
                "requestBody": {
                    "required": bool(schema.get("required")),
                    "content": {"application/json": {"schema": schema}},
                },
                "responses": {
                    "200": {
                        "description": ("The result. `ok` false means the request was refused and "
                                        "`error` explains why — read it, do not retry blindly."),
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean"},
                                "result": {"type": "object",
                                           "description": "Structured result, when there is one.",
                                           "additionalProperties": True},
                                "text": {"type": "string",
                                         "description": "Markdown, for the tools that return prose."},
                                "error": {"type": "string"},
                            },
                        }}},
                    },
                    "403": {"description": "The token is valid but not allowed to do this."},
                    "404": {"description": "The token is not recognised."},
                },
            }
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Nobridge CRM",
            "version": "1.0.0",
            "description": (
                "Read and update Nobridge's M&A pipeline. Deals live on five boards chosen by a tag "
                "on their Company; the workflow, the fields and the follow-up ladders are all "
                "described by `crm_context`, which you should read before answering questions about "
                "how the pipeline works. Write operations do nothing unless `confirm` is true — "
                "without it they return the diff they would apply."),
        },
        "servers": [{"url": PUBLIC_BASE}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer",
                               "description": "An AI Access token, issued per person."}
            }
        },
        "security": [{"bearerAuth": []}],
        "paths": paths,
    }


if __name__ == "__main__":
    import json
    doc = document()
    print(json.dumps(doc, indent=2))
    n = len(doc["paths"])
    if n > MAX_OPERATIONS:
        raise SystemExit("%d operations exceeds ChatGPT's limit of %d" % (n, MAX_OPERATIONS))
