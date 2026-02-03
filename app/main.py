from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from config.services import SERVICES, SERVICE_CATEGORIES
from datetime import date, time, datetime
from app.booking.slots import generate_slots
from config.services import SERVICES


from config.site import SITE

def get_service_by_id(service_id: int):
    return next(
        (service for service in SERVICES if service["id"] == service_id),
        None
    )


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "pages/home.html",
        {
            "request": request,
            "site": SITE
        }
    )

@app.get("/policies", response_class=HTMLResponse)
async def policies(request: Request):
    return templates.TemplateResponse(
        "pages/policies.html",
        {"request": request}
    )

@app.get("/payments", response_class=HTMLResponse)
async def payments(request: Request):
    return templates.TemplateResponse(
        "pages/payments.html",
        {"request": request}
    )

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse(
        "pages/terms.html",
        {"request": request}
    )

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse(
        "pages/privacy.html",
        {"request": request}
    )


@app.get("/book", response_class=HTMLResponse)
def booking(request: Request):
    return templates.TemplateResponse(
        "pages/book.html",
        {"request": request}
    )


# @app.post("/book/confirm", response_class=HTMLResponse)
# async def confirm(
#     request: Request,
#     selected_time: str = Form(...),
#     selected_date: str = Form(...),
#     service_id: int = Form(...)
# ):
#     service = get_service_by_id(service_id)
#
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     # Deposit logic
#     if "price" in service:
#         deposit_amount = min(2000, service["price"])
#     else:
#         deposit_amount = 2000  # variable-price services default
#
#     # Deposit rules
#     if service["price"] <= 2000:
#         deposit_due = service["price"]
#     else:
#         deposit_due = 2000
#
#     return templates.TemplateResponse(
#         "pages/book_confirm.html",
#         {
#             "request": request,
#             "service": service,
#             "selected_date": selected_date,
#             "selected_time": selected_time,
#             "deposit_amount": deposit_amount,
#             "hold_minutes": 15,
#             "deposit_due": deposit_due,
#         }
#     )


@app.post("/api/booking/preview")
async def booking_preview(
    service_id: int = Form(...),
    selected_date: str = Form(...),
    selected_time: str = Form(...)
):
    service = get_service_by_id(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    # Deposit rules
    if service.get("price", 0) <= 2000:
        deposit_due = service["price"]
    else:
        deposit_due = 2000

    return {
        "service": service,
        "selected_date": selected_date,
        "selected_time": selected_time,
        "deposit_due": deposit_due,
        "hold_minutes": 15
    }
