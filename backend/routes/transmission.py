"""
backend/routes/transmission.py - Unified transmission endpoint
=============================================================
Accepts detections via HTTP, MQTT, and CoAP.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import logging
import os
import io

from ..database import get_db, Detection
from ..processing.classifier import ServerClassifier

logger = logging.getLogger(__name__)

router = APIRouter()


class DetectionCreate(BaseModel):
    device_id: str
    species: str
    confidence: float
    timestamp: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    battery_pct: Optional[int] = None
    temp_c: Optional[int] = None


@router.post("/api/transmit")
def receive_detection(payload: DetectionCreate, db: Session = Depends(get_db)):
    """
    Unified endpoint to receive detections from any transmission protocol.
    Can be called via HTTP, MQTT (via subscriber), or CoAP.
    """
    try:
        # Set timestamp if not provided
        if payload.timestamp is None:
            payload.timestamp = datetime.now(timezone.utc)

        # Check for duplicates
        existing = db.query(Detection).filter(
            Detection.device_id == payload.device_id,
            Detection.timestamp == payload.timestamp,
            Detection.species == payload.species
        ).first()
        
        if existing:
            logger.info(f"Duplicate detection ignored: {payload.device_id}, {payload.timestamp}, {payload.species}")
            return {"status": "duplicate", "message": "Detection already exists"}

        # Create new detection
        detection = Detection(
            device_id=payload.device_id,
            species=payload.species,
            confidence=payload.confidence,
            timestamp=payload.timestamp,
            latitude=payload.latitude,
            longitude=payload.longitude,
            battery_pct=payload.battery_pct,
            temp_c=payload.temp_c
        )
        
        db.add(detection)
        db.commit()
        db.refresh(detection)
        
        logger.info(f"Detection received via transmission endpoint: {payload.device_id}, {payload.species}")
        return {"status": "success", "id": detection.id}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing detection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/clips")
async def upload_audio_clip(
    file: UploadFile,
    device_id: str = Form(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    battery_pct: Optional[int] = Form(None),
    temp_c: Optional[int] = Form(None),
    classify: bool = Form(True),
    db: Session = Depends(get_db)
):
    """
    Upload audio clip for server-side classification.
    Used by low-powered devices (Arduino Nano, etc.) that cannot run inference locally.
    """
    try:
        # Create clips directory if it doesn't exist
        clips_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "clips")
        os.makedirs(clips_dir, exist_ok=True)
        
        # Save audio file
        file_path = os.path.join(clips_dir, f"{device_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{file.filename}")
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        logger.info(f"Audio clip saved: {file_path}")
        
        # Classify audio if requested
        detections = []
        if classify:
            try:
                import librosa
                classifier = ServerClassifier()
                
                # Load audio
                audio, sr = librosa.load(file_path, sr=16000)
                
                # Classify
                detections = classifier.classify(audio, sr)
                
                # Store detections in database
                for det in detections:
                    # Check for duplicates
                    existing = db.query(Detection).filter(
                        Detection.device_id == device_id,
                        Detection.timestamp == det["timestamp"],
                        Detection.species == det["species"]
                    ).first()
                    
                    if not existing:
                        detection = Detection(
                            device_id=device_id,
                            species=det["species"],
                            confidence=det["confidence"],
                            timestamp=det["timestamp"],
                            latitude=latitude,
                            longitude=longitude,
                            battery_pct=battery_pct,
                            temp_c=temp_c
                        )
                        db.add(detection)
                
                db.commit()
                logger.info(f"Classified {len(detections)} detections from audio clip")
                
            except Exception as e:
                logger.error(f"Classification failed: {e}")
                # Continue without classification
        
        return {
            "status": "success",
            "file_path": file_path,
            "detections": detections,
            "count": len(detections)
        }
        
    except Exception as e:
        logger.error(f"Error processing audio clip: {e}")
        raise HTTPException(status_code=500, detail=str(e))
