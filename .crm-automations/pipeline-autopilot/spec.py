"""Loads workflow_spec.py at runtime and maps its human names onto live CRM identifiers.

THE SPEC IS NOT COPIED HERE. `.crm-automations/dashboard/workflow_spec.py` is the single source for
the pipeline ruleset; this module imports it. Edit the spec and this automation's behaviour changes
with no code change, which is the entire point — the alternative is a fourth hand-kept copy of the
rules, and the last time there were four copies they disagreed and five chase ladders stopped dead.

Note the repo boundary: the spec lives in the PRIVATE VAV-TECH-2/nobridge-ops-dashboard repo,
this file lives in the PUBLIC nobridge-crm-ops repo. We import across the boundary at runtime and
never copy spec content into a public file.

Two name mappings live here, and both are derived rather than tabulated:

  stage/option label -> enum value    "Intro Meeting" -> INTRO_MEETING, "Follow Up (90)" ->
                                      FOLLOW_UP_90. Verified against all 28 live stage names and
                                      all 8 verdicts.
  field label -> API name             "NDA Sent At" -> ndaSentAt. This is the SAME _camel() the v2
                                      migration used to create the 45 new fields
                                      (.crm-migrate-v2/01_add_fields.py:48-50), so it agrees with
                                      the columns that actually exist by construction.
"""
import hashlib
import importlib.util
import os
import re
import sys

# Where the spec might be. VM first (that is the deployed copy the live run uses), then the
# sibling checkout for laptop dry runs.
_CANDIDATES = [
    os.environ.get("AUTOPILOT_SPEC_DIR"),
    "/opt/heydeal-automations-dashboard",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard"),
]

_spec = None
_spec_path = None


def _load():
    global _spec, _spec_path
    if _spec is not None:
        return _spec
    tried = []
    for base in _CANDIDATES:
        if not base:
            continue
        path = os.path.abspath(os.path.join(base, "workflow_spec.py"))
        tried.append(path)
        if not os.path.exists(path):
            continue
        spec = importlib.util.spec_from_file_location("workflow_spec", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["workflow_spec"] = mod
        spec.loader.exec_module(mod)
        _spec, _spec_path = mod, path
        return _spec
    raise SystemExit("workflow_spec.py not found. Looked in:\n  " + "\n  ".join(tried)
                     + "\nSet AUTOPILOT_SPEC_DIR to point at it.")


def spec():
    return _load()


def spec_path():
    _load()
    return _spec_path


def spec_sha():
    """sha256 of the spec file. Recorded on every run so a decision can be traced to its ruleset."""
    with open(spec_path(), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ── name mapping ───────────────────────────────────────────────────────────────────────────────

def enum_value(label):
    """Human option label -> Twenty SELECT value. 'Follow Up (90)' -> 'FOLLOW_UP_90'."""
    v = re.sub(r"[^A-Za-z0-9]+", "_", str(label).strip().upper())
    return v.strip("_")


def api_name(label):
    """Human field label -> Twenty API field name, exactly as the v2 migration derived it."""
    parts = str(label).replace("-", " ").split()
    if not parts:
        return ""
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


# The `sets` value vocabulary, documented in workflow_spec.py's header. Six kinds and no more; an
# unrecognised value is a preflight blocker rather than something quietly ignored, because a typo in
# the spec must not turn into a field the autopilot silently declines to write.
VALUE_KINDS = ("now", "enum", "loop_next", "judge", "clear", "offset")

# Which field types each kind can legally target. Checked by preflight, so `{"nextSteps": "now"}`
# is caught in the spec rather than at 03:00 against a live record.
KIND_TYPES = {
    "now": ("DATE_TIME", "DATE"),
    "loop_next": ("DATE_TIME", "DATE"),
    "offset": ("DATE_TIME", "DATE"),
    "enum": ("SELECT", "MULTI_SELECT"),
    "judge": None,   # anything - judgement supplies a value of the right shape
    "clear": None,   # anything nullable
}

_OFFSET_RE = re.compile(r"^\+(\d+)(bd|d)$")


def value_spec(v):
    """Parse a `sets` value into (kind, payload).

    ("now", None) · ("enum", "Hosted") · ("loop_next", None) · ("judge", None) ·
    ("clear", None) · ("offset", (90, "d")) · ("unknown", <raw>) when it matches nothing.
    """
    if v is None:
        return ("judge", None)          # prose fallback named a field but no value
    s = str(v).strip()
    if s == "now":
        return ("now", None)
    if s.startswith("@"):
        return ("enum", s[1:])
    if s in ("loop_next", "judge", "clear"):
        return (s, None)
    m = _OFFSET_RE.match(s)
    if m:
        return ("offset", (int(m.group(1)), m.group(2)))
    return ("unknown", s)


# ── accessors over the spec ────────────────────────────────────────────────────────────────────

def pipelines():
    return _load().PIPELINES


def pipeline(name):
    return _load().PIPELINES[name]


def loops():
    return _load().LOOPS


def loop(loop_id):
    return _load().LOOP_BY_ID.get(loop_id)


def stage_names(pipeline_name):
    """Stage display names, in board order."""
    return [n for n, _note, _new in pipeline(pipeline_name)["stages"]]


def stage_enums(pipeline_name):
    """Stage enum values, in board order. This is the ordering the one-step-forward clamp uses -
    the metadata API returns options in creation order, which is not display order."""
    return [enum_value(n) for n in stage_names(pipeline_name)]


def stage_notes(pipeline_name):
    return {n: note for n, note, _new in pipeline(pipeline_name)["stages"]}


def steps(pipeline_name):
    return pipeline(pipeline_name)["steps"]


def steps_for_stage(pipeline_name, stage_name):
    """Steps that apply at a stage: the stage's own, plus the 'Any' steps that fire anywhere."""
    return [s for s in steps(pipeline_name) if s["stage"] in (stage_name, "Any")]


def loops_for_stage(pipeline_name, stage_name):
    ids = {s["loop"] for s in steps_for_stage(pipeline_name, stage_name) if s.get("loop")}
    return [loop(i) for i in sorted(ids) if loop(i)]


# ── writes-prose extraction (Phase 0 only) ─────────────────────────────────────────────────────
# Until every step carries a machine-readable `sets`, this reads the prose `writes` string to find
# which fields a step claims to touch. It exists to FIND THE GAPS, not to drive behaviour: the
# preflight uses it to report what the spec says it writes versus what the CRM can actually hold.
# Once `sets` is populated, `step_sets()` below prefers it and this becomes a fallback.

# Fragments in `writes` that describe behaviour rather than a field.
_NOT_A_FIELD = {
    "now", "true", "false", "true/false", "the assignee", "the next touch", "cleared",
    "owner and due cleared", "owner cleared", "every loop stops", "the cadence stops",
    "their date", "on return", "when settled", "confirmed",
}


def _clauses(writes):
    if not writes or writes == "—":
        return []
    return [c.strip() for c in str(writes).split("·") if c.strip()]


def writes_fields(step):
    """[(fieldLabel, valueText|None)] mentioned in a step's prose `writes`. Best effort.

    The prose is written for humans, so a clause is not always a field. Two shapes to reject:
    a clause with a comma is a sentence, not a name ("CRM tasks, once approved" - B23/S23/F13
    describe task creation, not a column); and a clause with no `=` is only a field if it reads
    like a label ("Screening Notes", "Source", "Mandate") rather than a description.
    """
    out = []
    for clause in _clauses(step.get("writes")):
        if "," in clause:
            continue
        if "=" in clause:
            left, right = clause.split("=", 1)
            label, value = left.strip(), right.strip()
        else:
            label, value = clause.strip(), None
        low = label.lower()
        if low in _NOT_A_FIELD or low.startswith(("a fresh deal", "the ", "every ", "anyone ")):
            continue
        # "Contract Signed At on return", "Prospect Type confirmed", "Outcome set on every open ..."
        for tail in (" on return", " confirmed", " set on every open record on that mandate"):
            if low.endswith(tail):
                label = label[: -len(tail)].strip()
                break
        words = label.split()
        if not words or len(words) > 4:
            continue
        # A bare clause must look like a field label: every word capitalised.
        if value is None and not all(w[:1].isupper() for w in words):
            continue
        out.append((label, value))
    return out


def step_sets(step):
    """{apiFieldName: valueText|None} a step writes. Prefers the machine-readable `sets` when the
    spec carries one; falls back to reading the prose."""
    if isinstance(step.get("sets"), dict):
        return dict(step["sets"])
    return {api_name(lbl): val for lbl, val in writes_fields(step)}


if __name__ == "__main__":
    s = _load()
    print("spec:", spec_path())
    print("sha256:", spec_sha()[:16], "| loops:", len(s.LOOPS),
          "| pipelines:", ", ".join(s.PIPELINES))
    for name in s.PIPELINES:
        print("  %-12s %d stages, %d steps | %s"
              % (name, len(stage_names(name)), len(steps(name)), " ".join(stage_enums(name))))
