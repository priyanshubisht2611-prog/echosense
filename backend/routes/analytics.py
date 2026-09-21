from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import math

from ..database import get_db, Detection, DetectionHourly, DetectionDaily

router = APIRouter()


# ── Pydantic Schemas ────────────────────────────────────────────

class ActivityCurveOut(BaseModel):
    species: Optional[str]
    hours: List[int]          # 0–23
    mean_detections: List[float]
    peak_hour: int


class TopSpecies(BaseModel):
    species: str
    count: int


class NodeDiversityInfo(BaseModel):
    device_id: str
    shannon_index: float


class DiversityOut(BaseModel):
    species_richness: int
    total_detections: int
    shannon_index: float
    simpson_index: float
    top_species: List[TopSpecies]
    by_node: List[NodeDiversityInfo]


class PhenologyOut(BaseModel):
    species: str
    first_seen: Optional[datetime]
    last_seen: Optional[datetime]
    peak_14_day_start: Optional[datetime]
    peak_14_day_end: Optional[datetime]
    peak_count: int
    season_length_days: Optional[int]
    monthly_heatmap: List[float]
    yearly_heatmap: List[dict]  # [{year: int, day_of_year_counts: List[int]}]
    yearly_trends: List[dict]  # [{year: int, first_seen: date, last_seen: date}]


class TimelineOut(BaseModel):
    date: str
    count: int


class SiteDiversityOut(BaseModel):
    date: str
    shannon_index: float
    species_richness: int


# ── Routes ──────────────────────────────────────────────────────

@router.get("/api/analytics/activity-curve", response_model=ActivityCurveOut)
def activity_curve(
    species: Optional[str] = Query(None),
    device_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Group detections by hour of day (0–23) using hourly aggregates.
    Returns mean detections per hour and peak hour.
    """
    # Try to use hourly aggregates first (last 6 hours for dynamic demo mode)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    query = db.query(DetectionHourly).filter(DetectionHourly.hour >= cutoff)

    if species:
        query = query.filter(DetectionHourly.species == species)
    if device_id:
        query = query.filter(DetectionHourly.device_id == device_id)

    hourly_aggregates = query.all()

    if hourly_aggregates:
        # Count detections per hour from aggregates
        hour_counts = [0] * 24
        for agg in hourly_aggregates:
            hour_counts[agg.hour.hour] += agg.count

        # Find number of unique days to compute mean
        unique_days = len(set(agg.hour.date() for agg in hourly_aggregates)) or 1
        mean_detections = [round(c / unique_days, 2) for c in hour_counts]
    else:
        # Fallback to raw detections if no aggregates
        query = db.query(Detection)
        if species:
            query = query.filter(Detection.species == species)
        if device_id:
            query = query.filter(Detection.device_id == device_id)
        detections = query.all()

        hour_counts = [0] * 24
        for det in detections:
            hour_counts[det.timestamp.hour] += 1

        unique_days = len(set(det.timestamp.date() for det in detections)) or 1
        mean_detections = [round(c / unique_days, 2) for c in hour_counts]

    peak_hour = mean_detections.index(max(mean_detections)) if any(mean_detections) else 0

    return ActivityCurveOut(
        species=species,
        hours=list(range(24)),
        mean_detections=mean_detections,
        peak_hour=peak_hour,
    )


@router.get("/api/analytics/diversity", response_model=DiversityOut)
def diversity(
    device_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Compute biodiversity metrics over last 6 hours.
    - species_richness: number of unique species
    - shannon_index: Shannon diversity index
    - top_species: top 5 species by detection count
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)

    query = db.query(Detection).filter(Detection.timestamp >= cutoff)
    if device_id:
        query = query.filter(Detection.device_id == device_id)

    detections = query.all()

    # Count per species
    species_counts: dict[str, int] = {}
    for det in detections:
        species_counts[det.species] = species_counts.get(det.species, 0) + 1

    species_richness = len(species_counts)
    total = sum(species_counts.values()) or 1

    # Shannon index: H = -Σ (pi * ln(pi))
    shannon_index = 0.0
    for count in species_counts.values():
        p = count / total
        if p > 0:
            shannon_index -= p * math.log(p)
    shannon_index = round(shannon_index, 4)

    # Simpson's index: D = 1 - Σ(pi²)
    simpson_sum = 0.0
    for count in species_counts.values():
        p = count / total
        simpson_sum += p * p
    simpson_index = round(1 - simpson_sum, 4)

    # Top 5 species
    sorted_species = sorted(species_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_species = [TopSpecies(species=s, count=c) for s, c in sorted_species]

    # Calculate shannon index by node
    by_node = []
    node_counts = {}
    for det in detections:
        if det.device_id not in node_counts:
            node_counts[det.device_id] = {}
        node_counts[det.device_id][det.species] = node_counts[det.device_id].get(det.species, 0) + 1
        
    for d_id, sn_counts in node_counts.items():
        n_total = sum(sn_counts.values()) or 1
        n_shannon = 0.0
        for count in sn_counts.values():
            p = count / n_total
            if p > 0:
                n_shannon -= p * math.log(p)
        by_node.append({"device_id": d_id, "shannon_index": round(n_shannon, 4)})

    return DiversityOut(
        species_richness=species_richness,
        total_detections=len(detections),
        shannon_index=shannon_index,
        simpson_index=simpson_index,
        top_species=top_species,
        by_node=by_node,
    )


@router.get("/api/analytics/phenology", response_model=PhenologyOut)
def get_phenology(
    species: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    Compute phenology metrics for a given species:
    - First and last seen dates
    - Peak 14-day window
    - Monthly heat map (normalized active months)
    """
    query = db.query(Detection).filter(Detection.species == species).order_by(Detection.timestamp.asc())
    detections = query.all()

    if not detections:
        return PhenologyOut(
            species=species,
            first_seen=None,
            last_seen=None,
            peak_14_day_start=None,
            peak_14_day_end=None,
            peak_count=0,
            season_length_days=None,
            monthly_heatmap=[0.0] * 12
        )

    first_seen = detections[0].timestamp
    last_seen = detections[-1].timestamp
    season_length_days = max(1, (last_seen - first_seen).days)

    # Monthly heatmap (count per month)
    monthly_counts = [0] * 12
    for det in detections:
        monthly_counts[det.timestamp.month - 1] += 1
        
    max_month = max(monthly_counts) or 1
    monthly_heatmap = [round(c / max_month, 2) for c in monthly_counts]

    # Year × day-of-year heatmap (multi-year phenology)
    yearly_data = {}
    for det in detections:
        year = det.timestamp.year
        day_of_year = det.timestamp.timetuple().tm_yday
        if year not in yearly_data:
            yearly_data[year] = [0] * 366  # 366 days to handle leap years
        yearly_data[year][day_of_year] += 1

    yearly_heatmap = []
    for year in sorted(yearly_data.keys()):
        yearly_heatmap.append({
            "year": year,
            "day_of_year_counts": yearly_data[year]
        })

    # Multi-year trend tracking (first/last detection per year)
    yearly_first_last = {}
    for det in detections:
        year = det.timestamp.year
        if year not in yearly_first_last:
            yearly_first_last[year] = {"first": det.timestamp.date(), "last": det.timestamp.date()}
        else:
            if det.timestamp.date() < yearly_first_last[year]["first"]:
                yearly_first_last[year]["first"] = det.timestamp.date()
            if det.timestamp.date() > yearly_first_last[year]["last"]:
                yearly_first_last[year]["last"] = det.timestamp.date()

    yearly_trends = []
    for year in sorted(yearly_first_last.keys()):
        yearly_trends.append({
            "year": year,
            "first_seen": yearly_first_last[year]["first"],
            "last_seen": yearly_first_last[year]["last"]
        })

    # Peak 14-day window
    peak_start = None
    peak_count = 0
    
    # Sliding window logic
    for i, det_start in enumerate(detections):
        window_start = det_start.timestamp
        window_end = window_start + timedelta(days=14)
        count = 0
        for j in range(i, len(detections)):
            if detections[j].timestamp <= window_end:
                count += 1
            else:
                break
        if count > peak_count:
            peak_count = count
            peak_start = window_start

    return PhenologyOut(
        species=species,
        first_seen=first_seen,
        last_seen=last_seen,
        peak_14_day_start=peak_start,
        peak_14_day_end=peak_start + timedelta(days=14) if peak_start else None,
        peak_count=peak_count,
        season_length_days=season_length_days,
        monthly_heatmap=monthly_heatmap,
        yearly_heatmap=yearly_heatmap,
        yearly_trends=yearly_trends
    )


@router.get("/api/species/{name}/timeline", response_model=List[TimelineOut])
def species_timeline(name: str, db: Session = Depends(get_db)):
    """
    Return a list of {date, count} showing detections per day for a species.
    """
    results = (
        db.query(func.date(Detection.timestamp).label("date"), func.count(Detection.id).label("count"))
        .filter(Detection.species == name)
        .group_by(func.date(Detection.timestamp))
        .order_by(func.date(Detection.timestamp).asc())
        .all()
    )
    return [{"date": str(row[0]), "count": row[1]} for row in results]


@router.get("/api/sites/{site_id}/diversity", response_model=List[SiteDiversityOut])
def site_diversity_timeline(site_id: str, db: Session = Depends(get_db)):
    """
    Return a list of {date, shannon_index, species_richness} computed on a rolling 7-day window.
    """
    detections = (
        db.query(Detection)
        .filter(Detection.device_id == site_id)
        .order_by(Detection.timestamp.asc())
        .all()
    )
    
    if not detections:
        return []
        
    unique_dates = sorted(list(set(d.timestamp.date() for d in detections)))
    results = []
    
    for d_date in unique_dates:
        window_start = d_date - timedelta(days=6)
        window_end = d_date
        
        species_counts = {}
        for det in detections:
            det_date = det.timestamp.date()
            if window_start <= det_date <= window_end:
                species_counts[det.species] = species_counts.get(det.species, 0) + 1
                
        species_richness = len(species_counts)
        total = sum(species_counts.values()) or 1
        
        shannon_index = 0.0
        for count in species_counts.values():
            p = count / total
            if p > 0:
                shannon_index -= p * math.log(p)
        shannon_index = round(shannon_index, 4)
        
        results.append({
            "date": str(d_date),
            "shannon_index": shannon_index,
            "species_richness": species_richness
        })
        
    return results

@router.get("/api/analytics/shannon-timeline")
def shannon_timeline(db: Session = Depends(get_db)):
    """Return daily Shannon index per device."""
    # Build daily diversity for every node. We can reuse the site_diversity_timeline logic for all nodes.
    devices = ["E-NK", "E-PG", "E-KB"]
    results = []
    
    for device_id in devices:
        # We can just fetch the daily pre-computed aggregates if they exist, or fallback to site_diversity_timeline logic
        # For simplicity, calculate from raw detections grouped by day
        detections = db.query(Detection).filter(Detection.device_id == device_id).order_by(Detection.timestamp.asc()).all()
        if not detections:
            continue
            
        unique_dates = sorted(list(set(d.timestamp.date() for d in detections)))
        for d_date in unique_dates:
            species_counts = {}
            for det in detections:
                if det.timestamp.date() == d_date:
                    species_counts[det.species] = species_counts.get(det.species, 0) + 1
                    
            if not species_counts: continue
            
            total = sum(species_counts.values()) or 1
            shannon_index = 0.0
            for count in species_counts.values():
                p = count / total
                if p > 0:
                    shannon_index -= p * math.log(p)
                    
            results.append({
                "device_id": device_id,
                "date": str(d_date),
                "shannon_index": round(shannon_index, 4)
            })
            
    return results

@router.get("/api/analytics/richness-timeline")
def richness_timeline(db: Session = Depends(get_db)):
    """Return daily Species Richness per device."""
    devices = ["E-NK", "E-PG", "E-KB"]
    results = []
    
    for device_id in devices:
        detections = db.query(Detection).filter(Detection.device_id == device_id).order_by(Detection.timestamp.asc()).all()
        if not detections:
            continue
            
        unique_dates = sorted(list(set(d.timestamp.date() for d in detections)))
        for d_date in unique_dates:
            species_set = set()
            for det in detections:
                if det.timestamp.date() == d_date:
                    species_set.add(det.species)
                    
            if not species_set: continue
            
            results.append({
                "device_id": device_id,
                "date": str(d_date),
                "species_richness": len(species_set)
            })
            
    return results

@router.get("/api/analytics/species-accumulation")
def species_accumulation(db: Session = Depends(get_db)):
    """Return the first time each species was discovered globally."""
    detections = db.query(Detection).order_by(Detection.timestamp.asc()).all()
    first_seen = {}
    
    for det in detections:
        if det.species not in first_seen:
            first_seen[det.species] = str(det.timestamp.date())
            
    results = [{"species": s, "first_seen_date": d} for s, d in first_seen.items()]
    return results
