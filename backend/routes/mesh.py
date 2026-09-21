"""
Mesh network analytics and topology endpoints for EchoSense backend.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

from backend.database import get_db
from backend.models import MeshTopology, Device

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/mesh/topology")
def get_mesh_topology(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get current mesh network topology.
    
    Returns:
        - nodes: List of all devices in the network
        - links: List of mesh links between devices
        - stats: Network statistics
    """
    # Get all devices as nodes
    devices = db.query(Device).all()
    nodes = [
        {
            "id": d.id,
            "site_name": d.site_name,
            "lat": d.lat,
            "lng": d.lng,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            "battery_pct": d.battery_pct
        }
        for d in devices
    ]
    
    # Get mesh topology links
    links = db.query(MeshTopology).all()
    link_data = [
        {
            "source": l.source_device_id,
            "target": l.neighbor_device_id,
            "signal_strength": l.signal_strength,
            "hop_count": l.hop_count,
            "last_seen": l.last_seen.isoformat() if l.last_seen else None
        }
        for l in links
    ]
    
    # Calculate network statistics
    stats = {
        "total_nodes": len(nodes),
        "total_links": len(link_data),
        "avg_hop_count": sum(l.hop_count for l in links) / len(links) if links else 0,
        "avg_signal_strength": sum(l.signal_strength for l in links) / len(links) if links else 0,
        "active_links": len([l for l in links if l.last_seen and (datetime.now(timezone.utc) - l.last_seen.replace(tzinfo=timezone.utc)) < timedelta(minutes=5)])
    }
    
    return {
        "nodes": nodes,
        "links": link_data,
        "stats": stats
    }


@router.post("/api/mesh/topology")
def update_mesh_topology(topology: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Update mesh topology from edge device.
    
    Expected payload:
    {
        "device_id": "NODE-01",
        "neighbors": [
            {
                "device_id": "NODE-02",
                "ip": "192.168.1.2",
                "port": 9000,
                "signal_strength": -65.0
            }
        ],
        "routes": [
            {
                "destination": "NODE-03",
                "next_hop": "NODE-02",
                "hop_count": 2
            }
        ]
    }
    """
    device_id = topology.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    
    neighbors = topology.get("neighbors", [])
    
    # Update mesh topology links
    for neighbor in neighbors:
        neighbor_id = neighbor.get("device_id")
        if not neighbor_id:
            continue
        
        # Check if link already exists
        existing = db.query(MeshTopology).filter(
            MeshTopology.source_device_id == device_id,
            MeshTopology.neighbor_device_id == neighbor_id
        ).first()
        
        if existing:
            existing.signal_strength = neighbor.get("signal_strength", 0.0)
            existing.last_seen = datetime.now(timezone.utc)
        else:
            new_link = MeshTopology(
                source_device_id=device_id,
                neighbor_device_id=neighbor_id,
                signal_strength=neighbor.get("signal_strength", 0.0),
                hop_count=1,
                last_seen=datetime.now(timezone.utc)
            )
            db.add(new_link)
    
    db.commit()
    logger.info(f"[MESH] Updated topology for device {device_id} with {len(neighbors)} neighbors")
    
    return {"status": "ok", "message": "topology updated"}


@router.get("/api/mesh/stats")
def get_mesh_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get mesh network statistics and analytics.
    """
    # Get all topology links
    links = db.query(MeshTopology).all()
    
    # Calculate hop count distribution
    hop_distribution = {}
    for link in links:
        hc = link.hop_count
        hop_distribution[hc] = hop_distribution.get(hc, 0) + 1
    
    # Calculate signal strength distribution
    signal_ranges = {
        "excellent (> -50)": 0,
        "good (-50 to -70)": 0,
        "fair (-70 to -85)": 0,
        "poor (< -85)": 0
    }
    for link in links:
        sig = link.signal_strength
        if sig > -50:
            signal_ranges["excellent (> -50)"] += 1
        elif sig > -70:
            signal_ranges["good (-50 to -70)"] += 1
        elif sig > -85:
            signal_ranges["fair (-70 to -85)"] += 1
        else:
            signal_ranges["poor (< -85)"] += 1
    
    return {
        "total_links": len(links),
        "hop_count_distribution": hop_distribution,
        "signal_strength_distribution": signal_ranges,
        "avg_hop_count": sum(l.hop_count for l in links) / len(links) if links else 0,
        "avg_signal_strength": sum(l.signal_strength for l in links) / len(links) if links else 0
    }


@router.delete("/api/mesh/topology/{device_id}")
def clear_device_topology(device_id: str, db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Clear topology data for a specific device (useful when device goes offline).
    """
    db.query(MeshTopology).filter(
        MeshTopology.source_device_id == device_id
    ).delete()
    db.commit()
    
    logger.info(f"[MESH] Cleared topology for device {device_id}")
    
    return {"status": "ok", "message": f"topology cleared for {device_id}"}
