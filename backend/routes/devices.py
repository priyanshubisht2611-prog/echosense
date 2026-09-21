from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from ..database import get_db, Device, Detection

router = APIRouter()


# ── Pydantic Schemas ────────────────────────────────────────────

class DeviceCreate(BaseModel):
    id: str
    site_name: str
    lat: float
    lng: float
    battery_pct: int = 100


class TelemetryUpdate(BaseModel):
    battery_pct: Optional[int] = None
    temp_c: Optional[int] = None


class TelemetryHistory(BaseModel):
    timestamp: datetime
    battery_pct: int
    temp_c: Optional[int]


class DeviceOut(BaseModel):
    id: str
    site_name: str
    lat: float
    lng: float
    last_seen: datetime
    battery_pct: int
    status: str  # "online", "stale", or "offline"

    class Config:
        from_attributes = True


def _get_status(last_seen: Optional[datetime]) -> str:
    """Determine device status based on last_seen timestamp."""
    if last_seen is None:
        return "offline"
    now = datetime.now(timezone.utc)
    # Ensure last_seen is timezone-aware
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    delta = now - last_seen
    if delta < timedelta(hours=1):
        return "online"
    elif delta < timedelta(hours=24):
        return "stale"
    else:
        return "offline"


# ── Routes ──────────────────────────────────────────────────────

@router.post("/api/devices", response_model=DeviceOut)
def register_or_update_device(device: DeviceCreate, db: Session = Depends(get_db)):
    """Register a new device or update an existing one."""
    existing = db.query(Device).filter(Device.id == device.id).first()

    if existing:
        existing.site_name = device.site_name
        existing.lat = device.lat
        existing.lng = device.lng
        existing.battery_pct = device.battery_pct
        existing.last_seen = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return DeviceOut(
            id=existing.id,
            site_name=existing.site_name,
            lat=existing.lat,
            lng=existing.lng,
            last_seen=existing.last_seen,
            battery_pct=existing.battery_pct,
            status=_get_status(existing.last_seen),
        )

    new_device = Device(
        id=device.id,
        site_name=device.site_name,
        lat=device.lat,
        lng=device.lng,
        battery_pct=device.battery_pct,
        last_seen=datetime.now(timezone.utc),
    )
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    return DeviceOut(
        id=new_device.id,
        site_name=new_device.site_name,
        lat=new_device.lat,
        lng=new_device.lng,
        last_seen=new_device.last_seen,
        battery_pct=new_device.battery_pct,
        status=_get_status(new_device.last_seen),
    )


@router.get("/api/devices", response_model=List[DeviceOut])
def get_all_devices(db: Session = Depends(get_db)):
    """Return all devices with computed status: online (<1h), stale (<24h), offline (>24h)."""
    devices = db.query(Device).all()
    return [
        DeviceOut(
            id=d.id,
            site_name=d.site_name,
            lat=d.lat,
            lng=d.lng,
            last_seen=d.last_seen,
            battery_pct=d.battery_pct,
            status=_get_status(d.last_seen),
        )
        for d in devices
    ]


@router.patch("/api/devices/{device_id}/telemetry", response_model=DeviceOut)
def update_telemetry(device_id: str, telemetry: TelemetryUpdate, db: Session = Depends(get_db)):
    """Update battery_pct, temp_c, and last_seen for a device."""
    device = db.query(Device).filter(Device.id == device_id).first()

    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")

    if telemetry.battery_pct is not None:
        device.battery_pct = telemetry.battery_pct
    device.last_seen = datetime.now(timezone.utc)

    db.commit()
    db.refresh(device)
    return DeviceOut(
        id=device.id,
        site_name=device.site_name,
        lat=device.lat,
        lng=device.lng,
        last_seen=device.last_seen,
        battery_pct=device.battery_pct,
        status=_get_status(device.last_seen),
    )


@router.get("/api/devices/{device_id}/health", response_model=List[TelemetryHistory])
def get_device_health(device_id: str, db: Session = Depends(get_db)):
    """Get telemetry history for a device from detection records."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")

    detections = (
        db.query(Detection)
        .filter(Detection.device_id == device_id)
        .order_by(Detection.timestamp.desc())
        .limit(100)
        .all()
    )

    return [
        TelemetryHistory(
            timestamp=d.timestamp,
            battery_pct=d.battery_pct,
            temp_c=d.temp_c,
        )
        for d in detections
    ]
