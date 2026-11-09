"""Small helpers shared by the Schluter platforms."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_comfort_end(value) -> datetime | None:
    """Parse the cloud's ComfortEndTime ("dd/mm/yyyy HH:MM:SS +00:00", UTC).

    Returns an aware datetime, or None if the value is missing or not in that
    format.
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%d/%m/%Y %H:%M:%S %z")
    except ValueError:
        return None


def format_comfort_end(end: datetime) -> str:
    """Format an end time the way the cloud and the app store it (UTC)."""
    return end.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M:00 +00:00")


def next_schedule_event(schedules, now: datetime) -> datetime | None:
    """Return the start of the next active scheduled event after ``now``.

    ``schedules`` is the cloud's "Schedules" list: one entry per weekday group
    (WeekDayGrpNo 1-7 = Monday-Sunday), each with "Events" that have an
    "Active" flag and a local "Clock" time. ``now`` must be aware and in the
    thermostat's local time zone. Inactive events are skipped, as the app does.
    Returns None if the schedule has no usable event.
    """
    if not schedules:
        return None
    groups = {g.get("WeekDayGrpNo"): g.get("Events") or [] for g in schedules}
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        events = groups.get(day.isoweekday()) or []
        candidates = []
        for event in events:
            if not event.get("Active"):
                continue
            try:
                hour, minute = (int(x) for x in str(event["Clock"]).split(":")[:2])
            except (KeyError, ValueError):
                continue
            candidates.append(
                datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)
            )
        for start in sorted(candidates):
            if start > now:
                return start
    return None
