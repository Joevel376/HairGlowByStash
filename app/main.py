from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import Depends, HTTPException, status
import secrets

from datetime import date, datetime, timedelta
from collections import defaultdict
from app.booking.slots import generate_slots
from config.availability import AVAILABILITY
from config.availability import is_slot_locked
from email.message import EmailMessage
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import BackgroundTasks
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from sqlalchemy import desc

from config.services import SERVICES, SERVICE_CATEGORIES
from config.site import SITE
from config.availability import (
    lock_slot,
    release_slot,
    get_active_locks_for_date
)

from app.database import Base, engine, SessionLocal
from app.models.booking import Booking

load_dotenv()

# -------------------------
# APP INIT
# -------------------------

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def send_email(to_email: str, subject: str, html_content: str):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("ADMIN_USERNAME", "admin")
    correct_password = os.getenv("ADMIN_PASSWORD", "supersecure")

    username_match = secrets.compare_digest(credentials.username, correct_username)
    password_match = secrets.compare_digest(credentials.password, correct_password)

    if not (username_match and password_match):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


@app.get("/admin/dashboard")
async def admin_dashboard(
    request: Request,
    status: str = None,
    admin=Depends(verify_admin)
):
    db = SessionLocal()

    query = db.query(Booking)

    if status:
        query = query.filter(Booking.status == status)

    bookings = query.order_by(desc(Booking.created_at)).all()

    pending_count = db.query(Booking).filter(Booking.status == "pending").count()
    confirmed_count = db.query(Booking).filter(Booking.status == "confirmed").count()
    cancelled_count = db.query(Booking).filter(Booking.status == "cancelled").count()

    db.close()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "bookings": bookings,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            "cancelled_count": cancelled_count,
            "current_filter": status
        }
    )



# -------------------------
# DB INIT
# -------------------------

Base.metadata.create_all(bind=engine)


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
async def create_booking(
    payload: CreateBookingRequest,
    background_tasks: BackgroundTasks
):
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

        # Release 10-minute hold
        release_slot(payload.date, payload.time)

        # -------------------------
        # EMAIL SECTION
        # -------------------------

        base_url = os.getenv("BASE_URL")
        owner_email = os.getenv("OWNER_EMAIL")

        reschedule_link = f"{base_url}/reschedule/{booking.id}"
        cancel_link = f"{base_url}/cancel/{booking.id}"

        # Owner Email
        owner_html = f"""
        <h2 style="color:#ec4899;">New Booking Request</h2>

        <p><strong>Client:</strong> {payload.full_name}</p>
        <p><strong>Phone:</strong> {payload.phone}</p>
        <p><strong>Email:</strong> {payload.email}</p>

        <hr>

        <p><strong>Service:</strong> {payload.service_name}</p>
        <p><strong>Date:</strong> {payload.date}</p>
        <p><strong>Time:</strong> {payload.time}</p>

        <p><strong>Notes:</strong><br>{payload.notes or "None"}</p>

        <hr>

        <p style="color:#b45309;">
        ⚠ This booking is pending deposit confirmation.
        </p>

        <p>
        <a href="{base_url}/admin/confirm/{booking.id}" 
           style="background:#16a34a;color:white;padding:10px 18px;border-radius:6px;text-decoration:none;">
           Confirm Booking
        </a>
        </p>

        <p>
        <a href="{base_url}/admin/cancel/{booking.id}" 
           style="background:#dc2626;color:white;padding:10px 18px;border-radius:6px;text-decoration:none;">
           Cancel Booking
        </a>
        </p>
        """

        background_tasks.add_task(
            send_email,
            owner_email,
            "New Booking Request - Hair Glow By Stash",
            owner_html
        )

        # Customer Email
        customer_html = f"""
        <h2>Your Booking Request Has Been Received</h2>
        <p>Hi {payload.full_name},</p>
        <p>Your appointment request has been received.</p>

        <p><strong>Service:</strong> {payload.service_name}</p>
        <p><strong>Date:</strong> {payload.date}</p>
        <p><strong>Time:</strong> {payload.time}</p>

        <p>Please send your deposit receipt within 24 hours.</p>

        <hr>

        <p>
            <a href="{reschedule_link}">Reschedule</a> |
            <a href="{cancel_link}">Cancel Appointment</a>
        </p>
        """

        background_tasks.add_task(
            send_email,
            payload.email,
            "Booking Request Received - Hair Glow By Stash",
            customer_html
        )

        return {
            "success": True,
            "booking_id": booking.id
        }

    finally:
        db.close()



@app.get("/cancel/{booking_id}")
def cancel_booking(booking_id: int):
    db = SessionLocal()
    booking = db.query(Booking).filter(Booking.id == booking_id).first()

    if not booking:
        return {"error": "Booking not found"}

    booking.status = "cancelled"
    db.commit()
    db.close()

    return {"success": True, "message": "Booking cancelled"}


@app.get("/reschedule/{booking_id}")
def reschedule_page(booking_id: int):
    return {"message": "Reschedule flow coming next"}



@app.get("/admin/confirm/{booking_id}")
def confirm_booking(booking_id: int, background_tasks: BackgroundTasks):

    db = SessionLocal()
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    admin = Depends(verify_admin)

    if not booking:
        db.close()
        return {"error": "Booking not found"}

    if booking.status != "pending":
        db.close()
        return {"message": "Booking already processed"}

    booking.status = "confirmed"
    db.commit()

    # Send confirmation email to customer
    confirmation_html = f"""
    <h2>Your Appointment is Confirmed 🎉</h2>
    <p>Hi {booking.full_name},</p>

    <p>Your appointment has been confirmed.</p>

    <p><strong>Service:</strong> {booking.service_name}</p>
    <p><strong>Date:</strong> {booking.date}</p>
    <p><strong>Time:</strong> {booking.time}</p>


    <p>We look forward to seeing you!</p>
    """

    background_tasks.add_task(
        send_email,
        booking.email,
        "Appointment Confirmed - Hair Glow By Stash",
        confirmation_html
    )

    db.close()

    return {"success": True, "message": "Booking confirmed"}


@app.get("/admin/cancel/{booking_id}")
def owner_cancel_booking(booking_id: int, background_tasks: BackgroundTasks):

    db = SessionLocal()
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    admin = Depends(verify_admin)

    if not booking:
        db.close()
        return {"error": "Booking not found"}

    booking.status = "cancelled"
    db.commit()

    # notify client
    cancel_html = f"""
    <h2>Your Appointment Was Cancelled</h2>
    <p>Hi {booking.full_name},</p>
    <p>Your booking has been cancelled.</p>

    <p>If this was unexpected, please contact the salon.</p>
    """

    background_tasks.add_task(
        send_email,
        booking.email,
        "Appointment Cancelled - Hair Glow By Stash",
        cancel_html
    )

    db.close()

    return {"success": True, "message": "Booking cancelled"}


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


scheduler = BackgroundScheduler()

@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(cleanup_expired_bookings, "interval", minutes=10)
    scheduler.start()

@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()
