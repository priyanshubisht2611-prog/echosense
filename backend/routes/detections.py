from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, field_validator
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from collections import defaultdict
import csv
import io
import logging
import threading

from ..database import get_db, Detection, Device
from ..logic.binary_parser import parse_binary_payload

router = APIRouter()

# Global rate limiting cache: device_id -> list of timestamps
rate_limit_store = defaultdict(list)
rate_limit_lock = threading.Lock()


# ── Pydantic Schemas ────────────────────────────────────────────

class DetectionCreate(BaseModel):
    device_id: str
    species: str
    confidence: float
    timestamp: datetime
    latitude: float
    longitude: float
    battery_pct: int
    temp_c: int

    @field_validator("confidence")
    @classmethod
    def confidence_must_be_valid(cls, v):
        if v < 0.3:
            raise ValueError("confidence must be >= 0.3")
        return v


class DetectionOut(BaseModel):
    id: int
    device_id: str
    species: str
    confidence: float
    timestamp: datetime
    latitude: float
    longitude: float
    battery_pct: int
    temp_c: int

    class Config:
        from_attributes = True


class SpeciesCount(BaseModel):
    species: str
    count: int


# ── Routes ──────────────────────────────────────────────────────

@router.post("/api/detections", response_model=List[DetectionOut])
def create_detections(detections: List[DetectionCreate], db: Session = Depends(get_db)):
    """
    Accept a JSON list of detection objects.
    - Validates confidence >= 0.3 (handled by Pydantic)
    - Checks for duplicate (device_id + timestamp + species) before inserting
    - Applies rate limiting and bounds checking
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=60)
    
    device_counts = defaultdict(int)
    for det in detections:
        device_counts[det.device_id] += 1
        
    for device_id, count in device_counts.items():
        rate_limit_store[device_id] = [t for t in rate_limit_store[device_id] if t > window_start]
        if len(rate_limit_store[device_id]) + count > 1000:
            logging.warning(f"Rate limit exceeded for device_id: {device_id}")
            raise HTTPException(status_code=429, detail="rate limit exceeded")
            
    device_map = {}
    for det in detections:
        if det.device_id not in device_map:
            device_map[det.device_id] = db.query(Device).filter(Device.id == det.device_id).first()
            
        device = device_map[det.device_id]
        if device:
            if abs(det.latitude - device.lat) > 0.1 or abs(det.longitude - device.lng) > 0.1:
                raise HTTPException(status_code=400, detail="coordinates out of bounds for device")

    for device_id, count in device_counts.items():
        rate_limit_store[device_id].extend([now] * count)

    created = []
    for det in detections:
        # Check for duplicate
        existing = db.query(Detection).filter(
            Detection.device_id == det.device_id,
            Detection.timestamp == det.timestamp,
            Detection.species == det.species,
        ).first()

        if existing:
            continue  # Skip duplicates silently

        new_detection = Detection(
            device_id=det.device_id,
            species=det.species,
            confidence=det.confidence,
            timestamp=det.timestamp,
            latitude=det.latitude,
            longitude=det.longitude,
            battery_pct=det.battery_pct,
            temp_c=det.temp_c,
        )
        db.add(new_detection)
        created.append(new_detection)

    db.commit()
    for d in created:
        db.refresh(d)

    return created


@router.post("/api/ingest/binary")
async def ingest_binary(request: Request, db: Session = Depends(get_db)):
    """
    Accept a raw 22-byte LoRa-style binary payload.
    - Decodes with logic.binary_parser.parse_binary_payload
    - Checks for duplicate (device_id + timestamp + species)
    - Upserts Device.last_seen so the node stays "online" while transmitting
    """
    body = await request.body()
    try:
        data = parse_binary_payload(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    device_id = data["device_id"]
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=60)
    
    rate_limit_store[device_id] = [t for t in rate_limit_store[device_id] if t > window_start]
    if len(rate_limit_store[device_id]) + 1 > 1000:
        logging.warning(f"Rate limit exceeded for device_id: {device_id}")
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    # ── Upsert device — create on first contact, heartbeat on every packet ──
    device = db.query(Device).filter(Device.id == device_id).first()
    if device:
        if abs(data["latitude"] - device.lat) > 0.1 or abs(data["longitude"] - device.lng) > 0.1:
            raise HTTPException(status_code=400, detail="coordinates out of bounds for device")
            
        device.last_seen = datetime.now(timezone.utc)
        if data.get("battery_pct") is not None:
            device.battery_pct = data["battery_pct"]
    else:
        # Auto-register with coords embedded in the binary payload
        device = Device(
            id=data["device_id"],
            site_name=data["device_id"],   # dashboard can rename later
            lat=data.get("latitude", 0.0),
            lng=data.get("longitude", 0.0),
            battery_pct=data.get("battery_pct", 100),
            last_seen=datetime.now(timezone.utc),
        )
        db.add(device)
    db.commit()

    # ── Check for duplicate detection ───────────────────────────────────
    existing = db.query(Detection).filter(
        Detection.device_id == data["device_id"],
        Detection.timestamp == data["timestamp"],
        Detection.species == data["species"],
    ).first()

    if existing:
        return {"status": "ok", "message": "duplicate ignored"}

    new_detection = Detection(
        device_id=data["device_id"],
        species=data["species"],
        confidence=data["confidence"],
        timestamp=data["timestamp"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        battery_pct=data["battery_pct"],
        temp_c=data["temp_c"],
    )
    db.add(new_detection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "ok", "message": "duplicate ignored"}

    with rate_limit_lock:
        rate_limit_store[device_id].append(now)

    return {"status": "ok", "message": "ingested"}



@router.get("/api/detections", response_model=List[DetectionOut])
def get_detections(
    device_id: Optional[str] = Query(None),
    species: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    """
    Query detections with optional filters.
    Returns list ordered by timestamp descending.
    """
    query = db.query(Detection)

    if device_id:
        query = query.filter(Detection.device_id == device_id)
    if species:
        query = query.filter(Detection.species == species)

    return query.order_by(Detection.timestamp.desc()).limit(limit).all()


@router.get("/api/detections/today")
def get_today_detections_count(db: Session = Depends(get_db)):
    """
    Returns the total count of detections for the current day.
    """
    today = datetime.now(timezone.utc).date()
    start_of_today = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    count = db.query(func.count(Detection.id)).filter(Detection.timestamp >= start_of_today).scalar()
    return {"count": count}


@router.get("/api/species", response_model=List[SpeciesCount])
def get_species(db: Session = Depends(get_db)):
    """
    Returns list of distinct species with total detection count.
    """
    results = (
        db.query(Detection.species, func.count(Detection.id).label("count"))
        .group_by(Detection.species)
        .order_by(func.count(Detection.id).desc())
        .all()
    )
    return [SpeciesCount(species=row[0], count=row[1]) for row in results]


@router.post("/api/clips")
async def upload_clip(file: UploadFile, db: Session = Depends(get_db)):
    """
    Upload an audio clip associated with a detection.
    Stores the clip and returns its URL.
    """
    # Validate file type
    if not file.filename.endswith(('.wav', '.mp3', '.ogg')):
        raise HTTPException(status_code=400, detail="Only audio files (wav, mp3, ogg) are supported")
    
    # In a real implementation, this would store the file and return a URL
    # For now, just return success with file info
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "status": "uploaded",
        "message": "Clip upload endpoint placeholder - actual storage not implemented"
    }


@router.get("/api/export")
def export_detections(format: str = Query(..., pattern="^(csv|geojson)$"), db: Session = Depends(get_db)):
    """
    Exports all detections in CSV or GeoJSON format.
    """
    detections = db.query(Detection).all()
    
    if format == "csv":
        def iter_csv():
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "device_id", "species", "confidence", "timestamp", "latitude", "longitude"])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            
            for d in detections:
                writer.writerow([
                    d.id, d.device_id, d.species, d.confidence,
                    d.timestamp.isoformat(), d.latitude, d.longitude
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
                
        return StreamingResponse(
            iter_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=export.csv"}
        )
        
    elif format == "geojson":
        features = []
        for d in detections:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [d.longitude, d.latitude]
                },
                "properties": {
                    "id": d.id,
                    "device_id": d.device_id,
                    "species": d.species,
                    "confidence": d.confidence,
                    "timestamp": d.timestamp.isoformat()
                }
            })
        return {"type": "FeatureCollection", "features": features}
