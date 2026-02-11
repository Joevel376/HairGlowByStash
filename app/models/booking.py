from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from app.database import Base

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)

    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=False)
    notes = Column(String)

    service_name = Column(String)
    addons = Column(String)

    date = Column(String, index=True)
    time = Column(String)

    duration = Column(Integer)

    status = Column(String, default="pending")

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
