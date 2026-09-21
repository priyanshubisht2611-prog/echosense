"""
backend/logic/mqtt_subscriber.py - MQTT Subscriber for Backend
============================================================
Receives detections via MQTT and stores them in the database.
"""

import logging
import json
from typing import Optional
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from ..database import SessionLocal, Detection

logger = logging.getLogger(__name__)


class MQTTSubscriber:
    """
    MQTT subscriber that receives detections and stores them in the database.
    """
    
    def __init__(
        self,
        broker: str = "localhost",
        port: int = 1883,
        topic: str = "echosense/detections",
        username: Optional[str] = None,
        password: Optional[str] = None
    ):
        """
        Initialize MQTT subscriber.
        
        Args:
            broker: MQTT broker host
            port: MQTT broker port
            topic: MQTT topic to subscribe to
            username: MQTT username (optional)
            password: MQTT password (optional)
        """
        if not MQTT_AVAILABLE:
            raise ImportError("paho-mqtt not installed. Install with: pip install paho-mqtt")
        
        self.broker = broker
        self.port = port
        self.topic = topic
        self.username = username
        self.password = password
        self.client = None
        self.connected = False
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback for MQTT connection."""
        if rc == 0:
            logger.info(f"Connected to MQTT broker: {self.broker}:{self.port}")
            client.subscribe(self.topic)
            logger.info(f"Subscribed to topic: {self.topic}")
            self.connected = True
        else:
            logger.error(f"MQTT connection failed with code {rc}")
    
    def on_message(self, client, userdata, msg):
        """Callback for received MQTT messages."""
        try:
            payload = json.loads(msg.payload.decode())
            
            # Extract detection data
            device_id = payload.get("device_id")
            species = payload.get("species")
            confidence = payload.get("confidence")
            timestamp_str = payload.get("timestamp")
            latitude = payload.get("latitude")
            longitude = payload.get("longitude")
            battery_pct = payload.get("battery_pct")
            temp_c = payload.get("temp_c")
            
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
                    logger.info(f"Stored detection from MQTT: {device_id}, {species}")
                else:
                    logger.info(f"Duplicate detection from MQTT ignored: {device_id}, {species}")
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing MQTT detection: {e}")
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
    
    def start(self):
        """Start MQTT subscriber."""
        if self.client is not None:
            logger.warning("MQTT client already started")
            return
        
        self.client = mqtt.Client()
        
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
        
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            logger.info(f"MQTT subscriber started on {self.broker}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to start MQTT subscriber: {e}")
    
    def stop(self):
        """Stop MQTT subscriber."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            self.connected = False
            logger.info("MQTT subscriber stopped")


# Global MQTT subscriber instance
_mqtt_subscriber: Optional[MQTTSubscriber] = None


def start_mqtt_subscriber(
    broker: str = "localhost",
    port: int = 1883,
    topic: str = "echosense/detections",
    username: Optional[str] = None,
    password: Optional[str] = None
):
    """Start global MQTT subscriber."""
    global _mqtt_subscriber
    if _mqtt_subscriber is None:
        _mqtt_subscriber = MQTTSubscriber(broker, port, topic, username, password)
        _mqtt_subscriber.start()
    return _mqtt_subscriber


def stop_mqtt_subscriber():
    """Stop global MQTT subscriber."""
    global _mqtt_subscriber
    if _mqtt_subscriber:
        _mqtt_subscriber.stop()
        _mqtt_subscriber = None
