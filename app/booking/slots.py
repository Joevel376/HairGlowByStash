from datetime import datetime, date, time, timedelta
from typing import List, Tuple

from config.availability import AVAILABILITY
from config.services import SERVICES


SLOT_INTERVAL_MINUTES = 15


# -------------------------
# Helpers
# -------------------------

def parse_time(t: str) -> time:
    """Convert 'HH:MM' → datetime.time"""
    hour, minute = map(int, t.split(":"))
    return time(hour=hour, minute=minute)


def combine_date_time(d: date, t: time) -> datetime:
    return datetime.combine(d, t)


# -------------------------
# Core Slot Generator
# -------------------------

def generate_slots(
    target_date: date,
    service_duration_minutes: int,
    overrides: List[Tuple[time | None, time | None]] = None,
    existing_bookings: List[Tuple[datetime, datetime]] = None,
) -> List[str]:
    """
    Returns list of valid slot start datetimes
    """

    overrides = overrides or []
    existing_bookings = existing_bookings or []

    weekday = target_date.weekday()

    # If no availability for this weekday → closed
    if weekday not in AVAILABILITY:
        return []

    start_str, end_str = AVAILABILITY[weekday]
    day_start = combine_date_time(target_date, parse_time(start_str))
    day_end = combine_date_time(target_date, parse_time(end_str))

    slots = []
    cursor = day_start
    duration = timedelta(minutes=service_duration_minutes)
    interval = timedelta(minutes=SLOT_INTERVAL_MINUTES)

    while cursor + duration <= day_end:
        candidate_start = cursor
        candidate_end = cursor + duration

        if _is_blocked(candidate_start, candidate_end, overrides):
            cursor += interval
            continue

        if _overlaps_booking(candidate_start, candidate_end, existing_bookings):
            cursor += interval
            continue

        slots.append(candidate_start.strftime("%H:%M"))
        cursor += interval

    return slots


# -------------------------
# Conflict Checks
# -------------------------

def _is_blocked(
    start: datetime,
    end: datetime,
    overrides: List[Tuple[time | None, time | None]],
) -> bool:
    """
    Checks availability overrides
    """
    for block_start, block_end in overrides:
        # Full day blocked
        if block_start is None and block_end is None:
            return True

        block_start_dt = combine_date_time(start.date(), block_start)
        block_end_dt = combine_date_time(start.date(), block_end)

        if start < block_end_dt and end > block_start_dt:
            return True

    return False


def _overlaps_booking(
    start: datetime,
    end: datetime,
    bookings: List[Tuple[datetime, datetime]],
) -> bool:
    """
    Checks existing bookings
    """
    for booked_start, booked_end in bookings:
        if start < booked_end and end > booked_start:
            return True
    return False
