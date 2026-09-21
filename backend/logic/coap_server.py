"""
backend/logic/coap_server.py - CoAP Server for Backend
=======================================================
Receives detections via CoAP and stores them in the database.
"""

import logging
import json
from typing import Optional
from datetime import datetime, timezone

try:
    import aiocoap
    COAP_AVAILABLE = True
except ImportError:
    COAP_AVAILABLE = False

from ..database import SessionLocal, Detection

logger = logging.getLogger(__name__)


class CoAPServer:
    """
    CoAP server that receives detections and stores them in the database.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 5683):
        """
        Initialize CoAP server.
        
        Args:
            host: Host to bind to
            port: Port to bind to
        """
        if not COAP_AVAILABLE:
            raise ImportError("aiocoap not installed. Install with: pip install aiocoap")
        
        self.host = host
        self.port = port
        self.server = None
    
    async def handle_detection(self, request):
        """
        Handle CoAP POST request with detection data.
        """
        try:
            payload = request.payload.decode()
            data = json.loads(payload)
            
            # Extract detection data
            device_id = data.get("device_id")
            species = data.get("species")
            confidence = data.get("confidence")
            timestamp_str = data.get("timestamp")
            latitude = data.get("latitude")
            longitude = data.get("longitude")
            battery_pct = data.get("battery_pct")
            temp_c = data.get("temp_c")
            
            # Parse timestamp
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.now(timezone.utc)
            
            # Store in database
            db = SessionLocal()
            try:
                # Check for duplicates
                existing = db.query(Detection).filter(
                    Detection.device_id == device_id,
                    Detection.timestamp == timestamp,
                    Detection.species == species
                ).first()
                
                if not existing:
                    detection = Detection(
                        device_id=device_id,
                        species=species,
                        confidence=confidence,
                        timestamp=timestamp,
                        latitude=latitude,
                        longitude=longitude,
                        battery_pct=battery_pct,
                        temp_c=temp_c
                    )
                    db.add(detection)
                    db.commit()
                    logger.info(f"Stored detection from CoAP: {device_id}, {species}")
                    return aiocoap.Message(code=aiocoap.CHANGED, payload=b"Stored")
                else:
                    logger.info(f"Duplicate detection from CoAP ignored: {device_id}, {species}")
                    return aiocoap.Message(code=aiocoap.CHANGED, payload=b"Duplicate")
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing CoAP detection: {e}")
                return aiocoap.Message(code=aiocoap.INTERNAL_SERVER_ERROR, payload=str(e).encode())
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error processing CoAP message: {e}")
            return aiocoap.Message(code=aiocoap.BAD_REQUEST, payload=str(e).encode())
    
    async def start(self):
        """Start CoAP server."""
        if self.server is not None:
            logger.warning("CoAP server already started")
            return
        
        # Create CoAP site
        root = aiocoap.resource.Site()
        root.add_resource(['api', 'detections'], aiocoap.resource.Resource(self.handle_detection))
        
        # Create server
        self.server = await aiocoap.Context.create_server_context(
            site=root,
            bind=(self.host, self.port)
        )
        logger.info(f"CoAP server started on {self.host}:{self.port}")
    
    async def stop(self):
        """Stop CoAP server."""
        if self.server:
            await self.server.shutdown()
            self.server = None
            logger.info("CoAP server stopped")


# Global CoAP server instance
_coap_server: Optional[CoAPServer] = None


async def start_coap_server(host: str = "0.0.0.0", port: int = 5683):
    """Start global CoAP server."""
    global _coap_server
    if _coap_server is None:
        _coap_server = CoAPServer(host, port)
        await _coap_server.start()
    return _coap_server


async def stop_coap_server():
    """Stop global CoAP server."""
    global _coap_server
    if _coap_server:
        await _coap_server.stop()
        _coap_server = None
