from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from datetime import date, datetime, timedelta
from collections import defaultdict
from app.booking.slots import generate_slots
from config.availability import AVAILABILITY
from config.availability import is_slot_locked


from config.services import SERVICES, SERVICE_CATEGORIES
from config.site import SITE
from config.availability import (
    lock_slot,
    release_slot,
    get_active_locks_for_date
)

from app.database import Base, engine, SessionLocal
from app.models.booking import Booking


# -------------------------
# DB INIT
# -------------------------

Base.metadata.create_all(bind=engine)


# -------------------------
# APP INIT
# -------------------------

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# -------------------------
# HELPERS
# -------------------------

def get_service_by_id(service_id: int):
    return next(
        (service for service in SERVICES if service["id"] == service_id),
        None
    )


def group_services_by_category():
    grouped = defaultdict(list)
    for service in SERVICES:
        grouped[service["category"]].append(service)
    return dict(grouped)


# -------------------------
# PAGES
# -------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "pages/home.html",
        {
            "request": request,
            "site": SITE
        }
    )


@app.get("/book", response_class=HTMLResponse)
def booking(request: Request):
    return templates.TemplateResponse(
        "pages/book.html",
        {
            "request": request,
            "service_categories": SERVICE_CATEGORIES,
            "services_by_category": group_services_by_category(),
            "today": date.today().isoformat(),
        }
    )


@app.get("/policies", response_class=HTMLResponse)
async def policies(request: Request):
    return templates.TemplateResponse("pages/policies.html", {"request": request})


@app.get("/payments", response_class=HTMLResponse)
async def payments(request: Request):
    return templates.TemplateResponse("pages/payments.html", {"request": request})


@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("pages/terms.html", {"request": request})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("pages/privacy.html", {"request": request})


# -------------------------
# SLOT LOCKING (10 MIN)
# -------------------------

class SlotLockRequest(BaseModel):
    date: str
    time: str
    duration: int
    session_id: str | None = None


class SlotReleaseRequest(BaseModel):
    date: str
    time: str


@app.post("/api/lock-slot")
async def lock_time_slot(request: SlotLockRequest):
    success = lock_slot(
        request.date,
        request.time,
        request.duration,
        request.session_id
    )

    return {
        "success": success,
        "locked_until": (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    }


@app.post("/api/release-slot")
async def release_time_slot(request: SlotReleaseRequest):
    success = release_slot(request.date, request.time)
    return {"success": success}


@app.get("/api/locks/{date}")
async def get_locks_for_date(date: str):
    locks = get_active_locks_for_date(date)
    return {"date": date, "locks": locks}


class CreateBookingRequest(BaseModel):
    full_name: str
    phone: str
    email: str
    notes: str | None = None
    service_id: int
    service_name: str
    date: str
    time: str
    duration: int


@app.post("/api/create-booking")
async def create_booking(payload: CreateBookingRequest):
    db = SessionLocal()

    try:
        # Ensure slot is still locked
        locks = get_active_locks_for_date(payload.date)

        matching_lock = next(
            (lock for lock in locks if lock["time"] == payload.time),
            None
        )

        if not matching_lock:
            raise HTTPException(
                status_code=400,
                detail="This time slot is no longer reserved."
            )

        # Create booking
        booking = Booking(
            full_name=payload.full_name,
            phone=payload.phone,
            email=payload.email,
            notes=payload.notes,
            service_name=payload.service_name,
            date=payload.date,
            time=payload.time,
            duration=payload.duration,
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )

        db.add(booking)
        db.commit()
        db.refresh(booking)

        # Release temporary 10-min hold
        release_slot(payload.date, payload.time)

        return {
            "success": True,
            "booking_id": booking.id
        }

    finally:
        db.close()



# -------------------------
# BOOKING CREATION
# -------------------------

@app.get("/api/availability")
async def api_availability(date: str, duration: int):
    """
    Returns available time slots excluding locked slots
    """

    try:
        y, m, d = [int(x) for x in date.split("-")]
        date_obj = datetime(y, m, d).date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    # Generate all possible slots
    all_slots = generate_slots(date_obj, duration)

    # Filter out locked slots
    available_slots = [
        slot for slot in all_slots
        if not is_slot_locked(date, slot, duration)
    ]

    return {"slots": available_slots}


# -------------------------
# AUTO CANCEL EXPIRED (24HR)
# -------------------------

def cleanup_expired_bookings():
    db = SessionLocal()
    now = datetime.utcnow()

    db.query(Booking)\
        .filter(Booking.status == "pending")\
        .filter(Booking.expires_at < now)\
        .update({"status": "cancelled"})

    db.commit()
    db.close()