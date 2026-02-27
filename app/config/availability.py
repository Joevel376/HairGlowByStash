from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Business timezone
BUSINESS_TZ = ZoneInfo("America/Jamaica")

AVAILABILITY = {
    6: ("16:00", "23:00"),  # Sunday
    0: ("16:00", "23:00"),  # Monday
    1: ("16:00", "23:00"),  # Tuesday
    2: ("16:00", "23:00"),  # Wednesday
    3: ("06:00", "23:00"),  # Thursday
    4: ("06:00", "23:00"),  # Friday
    5: ("16:00", "23:00"),  # Saturday
}

# Temporary slot locks (in-memory)
# Key: "YYYY-MM-DD|HH:MM"
# Value: {"expires_at": datetime, "duration_minutes": int, "session_id": str}
TEMP_LOCKS = {}


def cleanup_expired_locks():
    """Remove expired locks"""
    now = datetime.now(BUSINESS_TZ)  # ✅ Fixed: Use Jamaica timezone
    expired_keys = [
        key for key, lock in TEMP_LOCKS.items()
        if lock["expires_at"] <= now
    ]
    for key in expired_keys:
        del TEMP_LOCKS[key]


def lock_slot(date_str: str, time_str: str, duration_minutes: int, session_id: str):
    """Lock a time slot for 10 minutes"""

    cleanup_expired_locks()

    key = f"{date_str}|{time_str}"

    existing = TEMP_LOCKS.get(key)

    # If already locked by someone else → deny
    if existing and existing["session_id"] != session_id:
        return False

    TEMP_LOCKS[key] = {
        "expires_at": datetime.now(BUSINESS_TZ) + timedelta(minutes=10),  # ✅ Fixed: Use Jamaica timezone
        "duration_minutes": duration_minutes,
        "session_id": session_id
    }

    return True



def release_slot(date_str: str, time_str: str, session_id: str):
    """Release a locked time slot (only owner can release)"""

    key = f"{date_str}|{time_str}"
    existing = TEMP_LOCKS.get(key)

    if not existing:
        return False

    if existing["session_id"] != session_id:
        return False  # Not owner

    TEMP_LOCKS.pop(key, None)
    return True


def is_slot_locked(date_str: str, time_str: str, duration_minutes: int) -> bool:
    """Check if a slot overlaps with any active locks"""
    cleanup_expired_locks()

    from datetime import datetime, timedelta

    # Parse the slot we're checking
    slot_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    slot_end = slot_datetime + timedelta(minutes=duration_minutes)

    for lock_key, lock_data in TEMP_LOCKS.items():
        lock_date_str, lock_time_str = lock_key.split("|")

        # Only check locks on the same date
        if lock_date_str != date_str:
            continue

        # Parse the locked slot
        lock_start = datetime.strptime(f"{lock_date_str} {lock_time_str}", "%Y-%m-%d %H:%M")
        lock_end = lock_start + timedelta(minutes=lock_data["duration_minutes"])

        # Check for overlap
        if slot_datetime < lock_end and slot_end > lock_start:
            return True

    return False


def get_active_locks_for_date(date_str: str):
    cleanup_expired_locks()

    locks = []
    for lock_key, lock_data in TEMP_LOCKS.items():
        lock_date, lock_time = lock_key.split("|")

        if lock_date == date_str:
            locks.append({
                "time": lock_time,
                "duration": lock_data["duration_minutes"],
                "expires_at": lock_data["expires_at"].isoformat(),
                "session_id": lock_data["session_id"]  # ✅ ADD THIS
            })

    return locks