"""Business-day and business-hours arithmetic for the loop schedules.

Everything is Asia/Jakarta, Mon-Fri, with per-board hours from workflow_spec.BH:
    buy 09:00-18:00 · sell 08:00-17:00 · fulfillment 09:00-17:00

Two rules that matter:

  A due date always lands inside business hours. A touch computed for 02:00 on a Sunday is not a
  thing anybody can do, so it moves to the next working morning. Nothing is ever moved backwards -
  that would make a chase due before the event that triggered it.

  `at_mode` decides how a loop's `at` list is read. "absolute" measures every entry from the anchor;
  "relative" measures each from the previous touch. See workflow_spec.py's header for why this had
  to be made explicit: L11's six-touch cadence is written "+2 BD · +5 BD · +14 d · +5 BD · +90 d ·
  +3 BD", which spans about 116 days read relatively and collapses onto day 3 read absolutely.
"""
import re
from datetime import datetime, time, timedelta

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Jakarta")
except Exception:                                    # pragma: no cover - stdlib since 3.9
    TZ = None

# The engine runs on Asia/Jakarta and so does the team; USER_TIMEZONE in the engine .env agrees.
TZ_NAME = "Asia/Jakarta"
BUSINESS_DAYS = (0, 1, 2, 3, 4)                      # Mon-Fri; Sat=5, Sun=6

_HOURS_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*$")
# "day 6" · "immediately" · "+90 days" · "+2 BD" · "+14 d" · "at the SLA"
_DAY_RE = re.compile(r"^day\s+(\d+)$", re.I)
_OFF_RE = re.compile(r"^\+\s*(\d+)\s*(bd|d|day|days)$", re.I)


def now():
    return datetime.now(TZ) if TZ else datetime.now()


def hours(side_hours):
    """'09:00–18:00' -> (time(9,0), time(18,0)). The separator is an en-dash in the spec."""
    m = _HOURS_RE.match(side_hours)
    if not m:
        raise ValueError("cannot parse business hours %r" % side_hours)
    a, b, c, d = (int(x) for x in m.groups())
    return time(a, b), time(c, d)


def is_business_day(dt):
    return dt.weekday() in BUSINESS_DAYS


def add_calendar_days(dt, n):
    return dt + timedelta(days=n)


def add_business_days(dt, n):
    """n business days after dt. n=0 returns dt untouched, even on a weekend - clamping is a
    separate decision, so that callers can tell 'zero days later' from 'the next working moment'."""
    if n == 0:
        return dt
    step = 1 if n > 0 else -1
    remaining, out = abs(n), dt
    while remaining:
        out = out + timedelta(days=step)
        if is_business_day(out):
            remaining -= 1
    return out


def clamp_to_hours(dt, side_hours):
    """Move dt forward to the nearest moment inside business hours. Never backwards."""
    start, end = hours(side_hours)
    out = dt
    for _ in range(14):                              # a fortnight of holidays would be unusual
        if not is_business_day(out):
            out = datetime.combine((out + timedelta(days=1)).date(), start,
                                   tzinfo=out.tzinfo)
            continue
        if out.timetz().replace(tzinfo=None) < start:
            return datetime.combine(out.date(), start, tzinfo=out.tzinfo)
        if out.timetz().replace(tzinfo=None) > end:
            out = datetime.combine((out + timedelta(days=1)).date(), start, tzinfo=out.tzinfo)
            continue
        return out
    return out


def parse_at(entry):
    """One `at` entry -> (kind, n, unit). kind is 'day' | 'offset' | 'sla'."""
    s = str(entry).strip()
    if s.lower() == "immediately":
        return ("day", 0, "d")
    if s.lower().startswith("at the sla"):
        return ("sla", None, None)
    m = _DAY_RE.match(s)
    if m:
        return ("day", int(m.group(1)), "d")
    m = _OFF_RE.match(s)
    if m:
        unit = "bd" if m.group(2).lower() == "bd" else "d"
        return ("offset", int(m.group(1)), unit)
    raise ValueError("cannot parse `at` entry %r" % entry)


def _advance(base, n, unit):
    return add_business_days(base, n) if unit == "bd" else add_calendar_days(base, n)


def touch_dates(loop, anchor, side_hours, sla_days=None):
    """Every touch date for one loop, given the anchor it counts from.

    Returns [(index, label, datetime)] with index 1-based, in order, each clamped into business
    hours. `sla_days` is required only by L5, whose first touch is written "at the SLA".
    """
    out, cursor = [], anchor
    mode = loop.get("at_mode")
    if mode not in ("absolute", "relative"):
        raise ValueError("loop %s has at_mode=%r" % (loop.get("id"), mode))

    for i, entry in enumerate(loop["at"], start=1):
        kind, n, unit = parse_at(entry)
        if kind == "sla":
            if sla_days is None:
                raise ValueError("loop %s touch %r needs sla_days" % (loop.get("id"), entry))
            when = add_calendar_days(anchor, sla_days)
        elif mode == "absolute":
            # Measured from the anchor every time, so the list is a set of milestones.
            when = _advance(anchor, n, unit)
        else:
            # Measured from the previous touch, so the list is a cadence of gaps.
            when = _advance(cursor, n, unit)
        cursor = when
        out.append((i, str(entry), clamp_to_hours(when, side_hours)))
    return out


def next_touch(loop, anchor, side_hours, at=None, sla_days=None):
    """The first touch strictly after `at` (default: now). Returns (index, label, dt) or None when
    the ladder is exhausted - which is the signal that on_exhaust applies."""
    ref = at or now()
    for idx, label, when in touch_dates(loop, anchor, side_hours, sla_days):
        if when > ref:
            return (idx, label, when)
    return None


def touches_elapsed(loop, anchor, side_hours, at=None, sla_days=None):
    """How many touches of this loop are already due. len(at) means exhausted."""
    ref = at or now()
    return sum(1 for _i, _l, when in touch_dates(loop, anchor, side_hours, sla_days) if when <= ref)


def parse_dt(value):
    """Twenty timestamps come back as ISO with a trailing Z; dates as YYYY-MM-DD."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=TZ)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ) if TZ else dt


def iso(dt):
    """The shape Twenty's REST API accepts for DATE_TIME."""
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z") if TZ \
        else dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def iso_date(dt):
    """The shape Twenty's REST API accepts for DATE."""
    return dt.date().isoformat()


if __name__ == "__main__":
    import spec
    anchor = datetime(2026, 8, 3, 10, 0, tzinfo=TZ)      # a Monday morning
    print("anchor: %s (%s)\n" % (anchor.isoformat(), anchor.strftime("%A")))
    for lp in spec.loops():
        side_hours = "09:00–18:00"
        sla = 10 if lp["id"] == "L5" else None
        rows = touch_dates(lp, anchor, side_hours, sla)
        span = (rows[-1][2] - anchor).days
        print("%-4s %-9s %-46s -> %s  (spans %d days)"
              % (lp["id"], lp["at_mode"], " · ".join(lp["at"]),
                 ", ".join(w.strftime("%d%b %H:%M") for _i, _l, w in rows), span))
