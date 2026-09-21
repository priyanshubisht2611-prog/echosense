import os
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Detection(Base):
    __tablename__ = "detections"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    species = Column(String, index=True)
    confidence = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    latitude = Column(Float)
    longitude = Column(Float)
    battery_pct = Column(Integer)
    temp_c = Column(Integer)
    hop_count = Column(Integer, default=0)  # Number of hops in mesh network

    __table_args__ = (
        UniqueConstraint('device_id', 'timestamp', 'species', name='uix_detection'),
    )

class Device(Base):
    __tablename__ = "devices"
    id = Column(String, primary_key=True, index=True)
    site_name = Column(String)
    lat = Column(Float)
    lng = Column(Float)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    battery_pct = Column(Integer)

class MeshTopology(Base):
    __tablename__ = "mesh_topology"
    id = Column(Integer, primary_key=True, index=True)
    source_device_id = Column(String, index=True)
    neighbor_device_id = Column(String, index=True)
    signal_strength = Column(Float)  # RSSI in dBm
    hop_count = Column(Integer, default=1)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint('source_device_id', 'neighbor_device_id', name='uix_mesh_link'),
    )


class DetectionHourly(Base):
    __tablename__ = "detections_hourly"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    species = Column(String, index=True)
    hour = Column(DateTime, index=True)
    count = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('device_id', 'species', 'hour', name='uix_hourly'),
    )


class DetectionDaily(Base):
    __tablename__ = "detections_daily"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    species = Column(String, index=True)
    date = Column(DateTime, index=True)
    count = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('device_id', 'species', 'date', name='uix_daily'),
    )


class DetectionWeekly(Base):
    __tablename__ = "detections_weekly"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    species = Column(String, index=True)
    week_start = Column(DateTime, index=True)
    count = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('device_id', 'species', 'week_start', name='uix_weekly'),
    )


class DetectionMonthly(Base):
    __tablename__ = "detections_monthly"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    species = Column(String, index=True)
    month = Column(DateTime, index=True)
    count = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('device_id', 'species', 'month', name='uix_monthly'),
    )
