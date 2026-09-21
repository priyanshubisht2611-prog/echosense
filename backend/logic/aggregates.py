"""
backend/logic/aggregates.py - Materialized aggregate refresh logic
=================================================================
Functions to populate and refresh materialized aggregate tables
(hourly, daily, weekly, monthly) for detection counts.
"""

from datetime import datetime, timedelta
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from ..database import Detection, DetectionHourly, DetectionDaily, DetectionWeekly, DetectionMonthly


def refresh_hourly_aggregates(db: Session, hours: int = 24):
    """
    Populate hourly aggregates for the last N hours.
    """
    # Get the datetime N hours ago
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    # Group detections by hour, device_id, and species
    results = (
        db.query(
            func.strftime('%Y-%m-%d %H:00:00', Detection.timestamp).label('hour'),
            Detection.device_id,
            Detection.species,
            func.count(Detection.id).label('count')
        )
        .filter(Detection.timestamp >= cutoff)
        .group_by(
            func.strftime('%Y-%m-%d %H:00:00', Detection.timestamp),
            Detection.device_id,
            Detection.species
        )
        .all()
    )
    
    # Upsert into hourly aggregates
    for hour, device_id, species, count in results:
        # Convert string to datetime
        hour_dt = datetime.strptime(hour, '%Y-%m-%d %H:%M:%S')
        existing = db.query(DetectionHourly).filter(
            DetectionHourly.device_id == device_id,
            DetectionHourly.species == species,
            DetectionHourly.hour == hour_dt
        ).first()
        
        if existing:
            existing.count = count
        else:
            db.add(DetectionHourly(
                device_id=device_id,
                species=species,
                hour=hour_dt,
                count=count
            ))
    
    db.commit()


def refresh_daily_aggregates(db: Session, days: int = 90):
    """
    Populate daily aggregates for the last N days.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    results = (
        db.query(
            func.date(Detection.timestamp).label('date'),
            Detection.device_id,
            Detection.species,
            func.count(Detection.id).label('count')
        )
        .filter(Detection.timestamp >= cutoff)
        .group_by(
            func.date(Detection.timestamp),
            Detection.device_id,
            Detection.species
        )
        .all()
    )
    
    for date, device_id, species, count in results:
        # Convert string to datetime
        date_dt = datetime.strptime(date, '%Y-%m-%d')
        existing = db.query(DetectionDaily).filter(
            DetectionDaily.device_id == device_id,
            DetectionDaily.species == species,
            DetectionDaily.date == date_dt
        ).first()
        
        if existing:
            existing.count = count
        else:
            db.add(DetectionDaily(
                device_id=device_id,
                species=species,
                date=date_dt,
                count=count
            ))
    
    db.commit()


def refresh_weekly_aggregates(db: Session, weeks: int = 104):
    """
    Populate weekly aggregates for the last N weeks.
    """
    cutoff = datetime.utcnow() - timedelta(weeks=weeks)
    
    results = (
        db.query(
            func.strftime('%Y-%W', Detection.timestamp).label('week_start'),
            Detection.device_id,
            Detection.species,
            func.count(Detection.id).label('count')
        )
        .filter(Detection.timestamp >= cutoff)
        .group_by(
            func.strftime('%Y-%W', Detection.timestamp),
            Detection.device_id,
            Detection.species
        )
        .all()
    )
    
    for week_start, device_id, species, count in results:
        # Convert string to datetime (ISO week format: YYYY-Www)
        year, week = map(int, week_start.split('-'))
        # Get the Monday of the ISO week
        week_dt = datetime.strptime(f"{year}-{week}-1", "%Y-%W-%w")
        existing = db.query(DetectionWeekly).filter(
            DetectionWeekly.device_id == device_id,
            DetectionWeekly.species == species,
            DetectionWeekly.week_start == week_dt
        ).first()
        
        if existing:
            existing.count = count
        else:
            db.add(DetectionWeekly(
                device_id=device_id,
                species=species,
                week_start=week_dt,
                count=count
            ))
    
    db.commit()


def refresh_monthly_aggregates(db: Session, months: int = 36):
    """
    Populate monthly aggregates for the last N months.
    """
    cutoff = datetime.utcnow() - timedelta(days=months * 30)
    
    results = (
        db.query(
            func.strftime('%Y-%m-01', Detection.timestamp).label('month'),
            Detection.device_id,
            Detection.species,
            func.count(Detection.id).label('count')
        )
        .filter(Detection.timestamp >= cutoff)
        .group_by(
            func.strftime('%Y-%m-01', Detection.timestamp),
            Detection.device_id,
            Detection.species
        )
        .all()
    )
    
    for month, device_id, species, count in results:
        # Convert string to datetime
        month_dt = datetime.strptime(month, '%Y-%m-%d')
        existing = db.query(DetectionMonthly).filter(
            DetectionMonthly.device_id == device_id,
            DetectionMonthly.species == species,
            DetectionMonthly.month == month_dt
        ).first()
        
        if existing:
            existing.count = count
        else:
            db.add(DetectionMonthly(
                device_id=device_id,
                species=species,
                month=month_dt,
                count=count
            ))
    
    db.commit()


def refresh_all_aggregates(db: Session):
    """
    Refresh all aggregate tables with their default time ranges.
    """
    refresh_hourly_aggregates(db, hours=24)
    refresh_daily_aggregates(db, days=90)
    refresh_weekly_aggregates(db, weeks=104)
    refresh_monthly_aggregates(db, months=36)
