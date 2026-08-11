"""Puts the pipeline autopilot's modules on sys.path so this service can import them.

NOTHING IS COPIED HERE. The autopilot already owns the pieces this service needs — the Twenty
transport, the board map, live field introspection, the read-only Postgres layer, the deterministic
rules, the validator and the audit store — and the whole reason autopilot writes and documentation
cannot drift is that they read one `workflow_spec.py`. A connector with its own copy of any of that
would be the fourth copy problem all over again, and the last time there were four copies they
disagreed and five chase ladders stopped dead.

So: `import deps` first, then `import crm`, `import spec`, `import rules` and the rest resolve to
/opt/nobridge-pipeline-autopilot (on the VM) or ../pipeline-autopilot (laptop). The autopilot's
own `spec.py` then finds `workflow_spec.py` the same way, from the deployed dashboard.

The import order matters and is load-bearing: this directory stays FIRST on sys.path so our
`store_ai.py` / `tools.py` are never shadowed, and the autopilot dir is appended after it, so
`import store` inside the autopilot's own modules still gets the autopilot's store and not ours.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Where the autopilot might be. VM first — that is the deployed copy the live service uses.
_CANDIDATES = [
    os.environ.get("AI_AUTOPILOT_DIR"),
    "/opt/nobridge-pipeline-autopilot",
    os.path.join(_HERE, "..", "pipeline-autopilot"),
]

AUTOPILOT_DIR = None


def _bootstrap():
    global AUTOPILOT_DIR
    if AUTOPILOT_DIR:
        return AUTOPILOT_DIR
    tried = []
    for base in _CANDIDATES:
        if not base:
            continue
        path = os.path.abspath(base)
        tried.append(path)
        if not os.path.exists(os.path.join(path, "crm.py")):
            continue
        if _HERE not in sys.path:
            sys.path.insert(0, _HERE)
        if path not in sys.path:
            sys.path.append(path)          # append, never insert: see the docstring
        AUTOPILOT_DIR = path
        return path
    raise SystemExit(
        "pipeline-autopilot not found. Looked in:\n  " + "\n  ".join(tried)
        + "\nSet AI_AUTOPILOT_DIR to point at it.")


_bootstrap()


def autopilot_dir():
    return AUTOPILOT_DIR


if __name__ == "__main__":
    import crm
    import spec
    import twclient as tw
    print("autopilot:", AUTOPILOT_DIR)
    print("spec:     ", spec.spec_path())
    print("spec sha: ", spec.spec_sha()[:16])
    print("mode:     ", "VM (engine .env)" if tw.on_vm() else "remote (minted)", "|", tw.host())
    print("boards:   ", ", ".join(crm.BOARDS))
