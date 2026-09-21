"""
backend/routes/processing.py - Audio Processing Endpoints
========================================================
Endpoints for mel spectrogram extraction and classification.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import numpy as np
import io
import logging

from ..database import get_db
from ..processing.mel_spectrogram import extract_mel_spectrogram
from ..processing.classifier import ServerClassifier

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize classifier (singleton)
_classifier_instance = None


def get_classifier():
    """Get or create classifier instance."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = ServerClassifier()
    return _classifier_instance


class MelSpectrogramRequest(BaseModel):
    sample_rate: int = 16000
    n_mels: int = 64
    frame_length: int = 25
    hop_length: int = 10
    apply_pre_emphasis: bool = True
    apply_hamming: bool = True
    apply_log: bool = True
    normalize: bool = False


@router.post("/api/process/spectrogram")
async def extract_spectrogram(
    file: UploadFile,
    params: MelSpectrogramRequest = MelSpectrogramRequest(),
):
    """
    Extract mel spectrogram from uploaded audio file.
    
    Accepts audio file (wav, mp3) and returns mel spectrogram.
    """
    try:
        # Read audio file
        import librosa
        audio, sr = librosa.load(io.BytesIO(await file.read()), sr=params.sample_rate)
        
        # Extract mel spectrogram
        mel_spec = extract_mel_spectrogram(
            audio=audio,
            sr=sr,
            n_mels=params.n_mels,
            frame_length=params.frame_length,
            hop_length=params.hop_length,
            apply_pre_emphasis=params.apply_pre_emphasis,
            apply_hamming=params.apply_hamming,
            apply_log=params.apply_log,
            normalize=params.normalize
        )
        
        return {
            "shape": mel_spec.shape,
            "data": mel_spec.tolist(),
            "sample_rate": sr
        }
        
    except Exception as e:
        logger.error(f"Mel spectrogram extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/process/classify")
async def classify_audio(
    file: UploadFile,
    confidence_threshold: float = 0.3,
    multi_label: bool = False
):
    """
    Classify audio using BirdNET server-side classifier.
    
    Accepts audio file (wav, mp3) and returns species detections.
    """
    try:
        import librosa
        classifier = get_classifier()
        
        # Read audio file
        audio, sr = librosa.load(io.BytesIO(await file.read()), sr=16000)
        
        # Update classifier threshold
        classifier.confidence_threshold = confidence_threshold
        
        # Classify
        if multi_label:
            detections = classifier.classify_multi_label(audio, sr)
        else:
            detections = classifier.classify(audio, sr)
        
        return {
            "detections": detections,
            "count": len(detections)
        }
        
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
