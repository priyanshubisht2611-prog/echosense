"""
backend/processing/classifier.py - Server-side Classification
===========================================================
Integrates BirdNET for server-side species classification with post-processing.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class ServerClassifier:
    """
    Server-side classifier using BirdNET with post-processing.
    """
    
    def __init__(
        self,
        confidence_threshold: float = 0.3,
        temporal_window_seconds: float = 5.0,
        min_detections_in_window: int = 2,
        unknown_threshold: float = 0.1
    ):
        """
        Initialize classifier with post-processing parameters.
        
        Args:
            confidence_threshold: Minimum confidence to accept detection (default 0.3)
            temporal_window_seconds: Time window for temporal deduplication (default 5.0)
            min_detections_in_window: Minimum detections in window to keep species (default 2)
            unknown_threshold: Confidence below which to classify as unknown (default 0.1)
        """
        self.confidence_threshold = confidence_threshold
        self.temporal_window_seconds = temporal_window_seconds
        self.min_detections_in_window = min_detections_in_window
        self.unknown_threshold = unknown_threshold
        
        # Detection buffer for temporal deduplication
        self.detection_buffer: List[Dict] = []
        
        # Try to load BirdNET
        try:
            from birdnetlib import BirdNETClassifier
            self.classifier = BirdNETClassifier()
            logger.info("BirdNET classifier loaded successfully")
        except ImportError:
            logger.warning("birdnetlib not installed. Install with: pip install birdnetlib")
            self.classifier = None
    
    def classify(
        self,
        audio: np.ndarray,
        sr: int,
        timestamp: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Classify audio and apply post-processing.
        
        Args:
            audio: Audio array
            sr: Sample rate
            timestamp: Detection timestamp (for temporal deduplication)
        
        Returns:
            List of detection dictionaries with post-processing applied
        """
        if self.classifier is None:
            logger.error("BirdNET classifier not available")
            return []
        
        # Run BirdNET classification
        try:
            detections = self.classifier.predict(audio, sr)
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return []
        
        # Apply post-processing
        processed = self.post_process(detections, timestamp)
        
        return processed
    
    def post_process(
        self,
        detections: List[Dict],
        timestamp: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Apply post-processing to detections.
        
        Args:
            detections: Raw detections from BirdNET
            timestamp: Detection timestamp
        
        Returns:
            Processed detections
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        processed = []
        
        for det in detections:
            species = det.get("species", "Unknown")
            confidence = det.get("confidence", 0.0)
            
            # Confidence thresholding
            if confidence < self.confidence_threshold:
                continue
            
            # Unknown sound detection
            if confidence < self.unknown_threshold:
                species = "Unknown"
            
            # Temporal deduplication
            if not self._is_duplicate(species, timestamp, confidence):
                processed.append({
                    "species": species,
                    "confidence": confidence,
                    "timestamp": timestamp,
                    "raw_detections": [det]
                })
                
                # Add to buffer
                self.detection_buffer.append({
                    "species": species,
                    "timestamp": timestamp,
                    "confidence": confidence
                })
        
        # Clean up old detections from buffer
        self._cleanup_buffer(timestamp)
        
        return processed
    
    def _is_duplicate(
        self,
        species: str,
        timestamp: datetime,
        confidence: float
    ) -> bool:
        """
        Check if detection is a duplicate within temporal window.
        
        Args:
            species: Species name
            timestamp: Detection timestamp
            confidence: Detection confidence
        
        Returns:
            True if duplicate, False otherwise
        """
        for buffered in self.detection_buffer:
            if (buffered["species"] == species and
                abs((timestamp - buffered["timestamp"]).total_seconds()) < self.temporal_window_seconds):
                # Keep the higher confidence detection
                if confidence <= buffered["confidence"]:
                    return True
        
        return False
    
    def _cleanup_buffer(self, current_time: datetime):
        """
        Remove old detections from buffer outside temporal window.
        
        Args:
            current_time: Current timestamp
        """
        cutoff = current_time - timedelta(seconds=self.temporal_window_seconds)
        self.detection_buffer = [
            d for d in self.detection_buffer
            if d["timestamp"] > cutoff
        ]
    
    def classify_multi_label(
        self,
        audio: np.ndarray,
        sr: int,
        timestamp: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Classify audio and return multiple species (multi-label).
        
        Args:
            audio: Audio array
            sr: Sample rate
            timestamp: Detection timestamp
        
        Returns:
            List of detection dictionaries (multiple species)
        """
        if self.classifier is None:
            logger.error("BirdNET classifier not available")
            return []
        
        # Run BirdNET classification
        try:
            detections = self.classifier.predict(audio, sr)
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return []
        
        # Return all detections above confidence threshold (multi-label)
        processed = []
        
        if timestamp is None:
            timestamp = datetime.now()
        
        for det in detections:
            confidence = det.get("confidence", 0.0)
            
            # Confidence thresholding
            if confidence < self.confidence_threshold:
                continue
            
            # Unknown sound detection
            species = det.get("species", "Unknown")
            if confidence < self.unknown_threshold:
                species = "Unknown"
            
            processed.append({
                "species": species,
                "confidence": confidence,
                "timestamp": timestamp,
                "raw_detections": [det]
            })
        
        return processed
