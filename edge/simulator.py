"""
edge/simulator.py — Edge audio-analysis simulator
==================================================
Processes every .wav file in a directory (or a single file), runs Voice
Activity Detection (VAD) and BirdNET species identification, discards
detections below a confidence threshold, then POSTs surviving detections to
a remote ingest endpoint.  Falls back to :class:`LocalBuffer` on network
failure so that no detections are lost.

Usage
-----
    # Normal mode – analyse real WAV files
    python simulator.py --audio-dir ./recordings --server http://localhost:8000/api/detections

    # Demo mode – generate fake detections without any real audio I/O
    python simulator.py --demo

    # Full option reference
    python simulator.py --help
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import struct

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

try:
    import aiocoap
    COAP_AVAILABLE = True
except ImportError:
    COAP_AVAILABLE = False

# Global Power Tracking (mA)
# Assuming a standard 2000mAh battery (2000 * 3600 mA-seconds capacity)
BATTERY_CAPACITY_MAS = 2000.0 * 3600.0
battery_mas = BATTERY_CAPACITY_MAS

# Demo Mode Time Acceleration
# 1 hour in simulation = 5 seconds in real life (720x speed)
_demo_simulation_time = int(time.time())
_demo_time_acceleration_enabled = False

def consume_power(rate_ma: float, duration_sec: float):
    global battery_mas
    battery_mas -= rate_ma * duration_sec
    return max(0, int((battery_mas / BATTERY_CAPACITY_MAS) * 100))

# VAD capture window tracking
capture_window_sec = 0.0
silence_discard_sec = 0.0

def _check_vad_log():
    global capture_window_sec, silence_discard_sec
    if capture_window_sec >= 600.0:
        pct = (silence_discard_sec / capture_window_sec) * 100
        logger.info("VAD silence_discard_pct for last 10-mins: %.1f%%", pct)
        capture_window_sec = 0.0
        silence_discard_sec = 0.0



# ---------------------------------------------------------------------------
# Optional heavy-weight imports (VAD / BirdNET) — fail gracefully
# ---------------------------------------------------------------------------

try:
    import webrtcvad  # pip install webrtcvad
    _WEBRTCVAD_AVAILABLE = True
except ImportError:
    _WEBRTCVAD_AVAILABLE = False

try:
    from birdnetlib import Recording  # pip install birdnetlib
    from birdnetlib.analyzer import Analyzer
    _BIRDNET_AVAILABLE = True
except ImportError:
    _BIRDNET_AVAILABLE = False

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))
from buffer import LocalBuffer  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("simulator")

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_SERVER_URL: str = "http://localhost:8000/api/detections"
DEFAULT_AUDIO_DIR: Path = Path("./recordings")
DEFAULT_CONFIDENCE: float = 0.65
DEFAULT_SLEEP: int = 5            # seconds between processing loops
REQUEST_TIMEOUT: int = 10         # seconds

# Fake species pool used in --demo mode
# Regional birds of Nainital & Kumaon Himalayas, Uttarakhand
_DEMO_SPECIES: List[str] = [
    "Pycnonotus leucogenys",      # Himalayan Bulbul
    "Urocissa erythroryncha",     # Red-billed Blue Magpie
    "Eumyias thalassinus",        # Verditer Flycatcher
    "Turdus boulboul",            # Grey-winged Blackbird
    "Lophura leucomelanos",       # Kalij Pheasant
    "Phoenicurus leucocephalus",  # White-capped Water Redstart
    "Phoenicurus fuliginosus",    # Plumbeous Water Redstart
    "Garrulax albogularis",       # White-throated Laughingthrush
    "Heterophasia capistrata",    # Rufous Sibia
    "Myophonus caeruleus",        # Blue Whistling Thrush
    "Spilopelia chinensis",       # Spotted Dove
    "Streptopelia orientalis",    # Oriental Turtle Dove
    "Spilornis cheela",           # Crested Serpent Eagle
    "Dendrocoptes auriceps",      # Brown-fronted Woodpecker
    "Yuhina gularis",             # Stripe-throated Yuhina
    "Nucifraga caryocatactes",   # Himalayan Nutcracker
    "Carpodacus erythrinus",      # Common Rosefinch
    "Phylloscopus xanthoschistos",# Grey-hooded Warbler
    "Niltava sundara",            # Rufous-bellied Niltava
    "Ficedula superciliaris",     # Ultramarine Flycatcher
]

# Weighted species distribution for realistic simulation
# Higher weight = more common, lower weight = rarer
_DEMO_SPECIES_WEIGHTS: Dict[str, float] = {
    # Common birds (high weight)
    "Pycnonotus leucogenys": 15.0,      # Himalayan Bulbul
    "Spilopelia chinensis": 12.0,       # Spotted Dove
    "Streptopelia orientalis": 10.0,    # Oriental Turtle Dove
    "Urocissa erythroryncha": 8.0,     # Red-billed Blue Magpie
    "Myophonus caeruleus": 7.0,        # Blue Whistling Thrush
    
    # Uncommon birds (medium weight)
    "Eumyias thalassinus": 5.0,        # Verditer Flycatcher
    "Turdus boulboul": 4.5,            # Grey-winged Blackbird
    "Phoenicurus leucocephalus": 4.0,  # White-capped Water Redstart
    "Phoenicurus fuliginosus": 3.5,    # Plumbeous Water Redstart
    "Garrulax albogularis": 3.0,       # White-throated Laughingthrush
    "Carpodacus erythrinus": 2.5,      # Common Rosefinch
    
    # Rare birds (low weight)
    "Heterophasia capistrata": 1.5,    # Rufous Sibia
    "Phylloscopus xanthoschistos": 1.2,# Grey-hooded Warbler
    "Yuhina gularis": 1.0,             # Stripe-throated Yuhina
    "Lophura leucomelanos": 0.8,       # Kalij Pheasant
    
    # Very rare birds (very low weight)
    "Spilornis cheela": 0.5,           # Crested Serpent Eagle
    "Dendrocoptes auriceps": 0.4,      # Brown-fronted Woodpecker
    "Nucifraga caryocatactes": 0.3,   # Himalayan Nutcracker
    "Niltava sundara": 0.2,            # Rufous-bellied Niltava
    "Ficedula superciliaris": 0.1,     # Ultramarine Flycatcher
}

# ---------------------------------------------------------------------------
# VAD helper
# ---------------------------------------------------------------------------


def _read_wav_pcm(wav_path: Path) -> tuple[bytes, int]:
    """
    Read a WAV file and return raw PCM bytes + sample rate.

    Limitations: mono, 16-bit PCM only (webrtcvad requirement).
    """
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if n_channels != 1 or sampwidth != 2:
        raise ValueError(
            f"{wav_path.name}: expected mono 16-bit PCM "
            f"(got channels={n_channels}, sampwidth={sampwidth})"
        )
    return raw, framerate


def run_vad(wav_path: Path, aggressiveness: int = 2) -> bool:
    """
    Return ``True`` if the WAV file contains voiced / bird-call audio.

    Uses webrtcvad when available; degrades gracefully to *always pass*
    when the library is not installed so that BirdNET can still run.

    Parameters
    ----------
    wav_path : Path
        Path to a mono, 16-bit PCM WAV file.
    aggressiveness : int
        webrtcvad aggressiveness level 0–3 (higher = more aggressive filtering).
    """
    if not _WEBRTCVAD_AVAILABLE:
        logger.debug("webrtcvad not available — skipping VAD for %s", wav_path.name)
        return True

    try:
        pcm, rate = _read_wav_pcm(wav_path)
    except (wave.Error, ValueError) as exc:
        logger.warning("VAD read error (%s): %s", wav_path.name, exc)
        return False

    # webrtcvad supports 8 / 16 / 32 kHz and 10 / 20 / 30 ms frames
    if rate not in (8000, 16000, 32000):
        logger.debug(
            "VAD: unsupported sample rate %d Hz for %s — skipping VAD",
            rate, wav_path.name,
        )
        return True

    vad = webrtcvad.Vad(aggressiveness)
    frame_duration_ms = 30            # ms
    frame_size = int(rate * frame_duration_ms / 1000) * 2  # bytes (16-bit)

    voiced_frames = 0
    total_frames = 0

    for i in range(0, len(pcm) - frame_size + 1, frame_size):
        frame = pcm[i : i + frame_size]
        if len(frame) < frame_size:
            break
        try:
            if vad.is_speech(frame, rate):
                voiced_frames += 1
        except Exception:
            pass
        total_frames += 1

    if total_frames == 0:
        return False

    voiced_ratio = voiced_frames / total_frames
    logger.debug(
        "VAD %s: %.1f%% voiced frames", wav_path.name, voiced_ratio * 100
    )
    return voiced_ratio >= 0.10  # at least 10 % voiced energy is enough


# ---------------------------------------------------------------------------
# BirdNET helper
# ---------------------------------------------------------------------------


def run_birdnet(wav_path: Path) -> List[Dict[str, Any]]:
    """
    Run BirdNET on *wav_path* and return a list of detection dicts.

    Each dict contains at minimum:
        ``species``    – scientific name
        ``common_name``– English common name
        ``confidence`` – float in [0, 1]
        ``start_time`` – start of detection window (seconds)
        ``end_time``   – end of detection window (seconds)

    Returns an empty list when BirdNET is not installed or the analysis fails.
    """
    if not _BIRDNET_AVAILABLE:
        logger.debug("birdnetlib not available — returning empty detections for %s", wav_path.name)
        return []

    try:
        analyzer = Analyzer()
        recording = Recording(
            analyzer,
            str(wav_path),
            min_conf=0.0,   # we apply our own threshold later
        )
        recording.analyze()
        detections = []
        for det in (recording.detections or []):
            detections.append({
                "species": det.get("scientific_name", det.get("species", "Unknown")),
                "common_name": det.get("common_name", "Unknown"),
                "confidence": float(det.get("confidence", 0.0)),
                "start_time": float(det.get("start_time", 0.0)),
                "end_time": float(det.get("end_time", 3.0)),
            })
        return detections
    except Exception as exc:
        logger.error("BirdNET failed on %s: %s", wav_path.name, exc)
        return []


# ---------------------------------------------------------------------------
# Demo-mode fake detection generator
# ---------------------------------------------------------------------------


def generate_fake_detections(wav_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Return 0–2 randomly generated detections for demo / testing purposes.

    Uses weighted species distribution for realistic simulation (rare birds appear rarely).
    Confidence varies based on species rarity (rare birds have lower confidence).
    """
    # 30% chance of no detections (silence), 40% chance of 1 detection, 30% chance of 2 detections
    n = random.choices([0, 1, 2], weights=[0.3, 0.4, 0.3])[0]
    
    if n == 0:
        return []
    
    filename = wav_path.name if wav_path else "demo_audio.wav"
    detections = []
    t = 0.0
    
    for _ in range(n):
        start = round(t, 2)
        end = round(start + 3.0, 2)
        t = end + random.uniform(0.5, 2.0)
        
        # Weighted random species selection
        species = random.choices(
            _DEMO_SPECIES, 
            weights=[_DEMO_SPECIES_WEIGHTS[s] for s in _DEMO_SPECIES]
        )[0]
        
        # Confidence varies based on species rarity (rarer birds have lower confidence)
        weight = _DEMO_SPECIES_WEIGHTS[species]
        # Normalize weight to 0-1 range for confidence calculation
        max_weight = max(_DEMO_SPECIES_WEIGHTS.values())
        min_weight = min(_DEMO_SPECIES_WEIGHTS.values())
        normalized_weight = (weight - min_weight) / (max_weight - min_weight)
        # Rarer birds (lower weight) have lower confidence range
        if normalized_weight > 0.7:
            # Common birds: high confidence
            conf_min, conf_max = 0.75, 1.0
        elif normalized_weight > 0.3:
            # Uncommon birds: medium confidence
            conf_min, conf_max = 0.65, 0.90
        else:
            # Rare birds: lower confidence
            conf_min, conf_max = 0.55, 0.80
        
        confidence = round(random.uniform(conf_min, conf_max), 4)
        
        detections.append({
            "species": species,
            "common_name": "Demo Bird",
            "confidence": confidence,
            "start_time": start,
            "end_time": end,
            "source_file": filename,
        })
    return detections


# ---------------------------------------------------------------------------
# Detection → payload
# ---------------------------------------------------------------------------


def build_payload(
    detection: Dict[str, Any],
    wav_path: Optional[Path],
    device_id: str,
) -> Dict[str, Any]:
    """Enrich a raw BirdNET detection dict with metadata before sending."""
    # Use simulation time if demo acceleration is enabled
    if _demo_time_acceleration_enabled:
        timestamp = datetime.fromtimestamp(_demo_simulation_time, tz=timezone.utc).isoformat()
    else:
        timestamp = datetime.now(tz=timezone.utc).isoformat()
    
    return {
        "device_id": device_id,
        "timestamp": timestamp,
        "audio_file": wav_path.name if wav_path else "demo",
        "species": detection.get("species", "Unknown"),
        "common_name": detection.get("common_name", "Unknown"),
        "confidence": detection.get("confidence", 0.0),
        "start_time": detection.get("start_time", 0.0),
        "end_time": detection.get("end_time", 0.0),
        "latitude": float(os.environ.get("EDGE_LAT", 0.0)),
        "longitude": float(os.environ.get("EDGE_LNG", 0.0)),
        "battery_pct": int(consume_power(0, 0)),
        "temp_c": 25,
    }

# Species index map for 22-byte binary LoRa packets (Nainital region)
SPECIES_LOOKUP_REV = {
    "Pycnonotus leucogenys":       0,   # Himalayan Bulbul
    "Urocissa erythroryncha":      1,   # Red-billed Blue Magpie
    "Eumyias thalassinus":         2,   # Verditer Flycatcher
    "Turdus boulboul":             3,   # Grey-winged Blackbird
    "Lophura leucomelanos":        4,   # Kalij Pheasant
    "Phoenicurus leucocephalus":   5,   # White-capped Water Redstart
    "Phoenicurus fuliginosus":     6,   # Plumbeous Water Redstart
    "Garrulax albogularis":        7,   # White-throated Laughingthrush
    "Heterophasia capistrata":     8,   # Rufous Sibia
    "Myophonus caeruleus":         9,   # Blue Whistling Thrush
    "Spilopelia chinensis":        10,  # Spotted Dove
    "Streptopelia orientalis":     11,  # Oriental Turtle Dove
    "Spilornis cheela":            12,  # Crested Serpent Eagle
    "Dendrocoptes auriceps":       13,  # Brown-fronted Woodpecker
    "Yuhina gularis":              14,  # Stripe-throated Yuhina
    "Nucifraga caryocatactes":    15,  # Himalayan Nutcracker
    "Carpodacus erythrinus":       16,  # Common Rosefinch
    "Phylloscopus xanthoschistos": 17,  # Grey-hooded Warbler
    "Niltava sundara":             18,  # Rufous-bellied Niltava
    "Ficedula superciliaris":      19,  # Ultramarine Flycatcher
}

def build_binary_payload(
    detection: Dict[str, Any],
    device_id: str,
) -> bytes:
    """Pack into 22-byte LoRa-style packets."""
    import time
    from datetime import datetime
    
    dev_id_bytes = device_id.encode('utf-8')[:4].ljust(4, b'\x00')
    # Use simulation time if demo acceleration is enabled
    if _demo_time_acceleration_enabled:
        ts = _demo_simulation_time
    else:
        ts = int(time.time())
    sp_name = detection.get("species", "Unknown")
    species_idx = SPECIES_LOOKUP_REV.get(sp_name, 999) # fallback
    conf = int(detection.get("confidence", 0.0) * 100)
    lat = float(os.environ.get("EDGE_LAT", 0.0))
    lng = float(os.environ.get("EDGE_LNG", 0.0))
    bat = consume_power(0, 0) # current battery pct
    temp = 25 # dummy temp
    
    # Pack into binary format
    return struct.pack('>4s I H B f f B b x', dev_id_bytes, ts, species_idx, conf, lat, lng, bat, temp)



# ---------------------------------------------------------------------------
# HTTP send with LocalBuffer fallback
# ---------------------------------------------------------------------------


def send_detection(
    payload: Any,
    server_url: str,
    buffer: LocalBuffer,
    is_binary: bool = False,
    mqtt_client: Any = None,
    mqtt_topic: str = "echosense/detections",
    coap_uri: str = None
) -> bool:
    try:
        # Publish via MQTT if client is available
        if mqtt_client and MQTT_AVAILABLE:
            try:
                payload_json = json.dumps(payload if not is_binary else {"binary": payload.hex()})
                mqtt_client.publish(mqtt_topic, payload_json)
                logger.info("✓ Published to MQTT: %s", mqtt_topic)
            except Exception as mqtt_exc:
                logger.warning("✗ MQTT publish failed: %s", mqtt_exc)

        # Send via CoAP if URI is available
        if coap_uri and COAP_AVAILABLE:
            try:
                import asyncio
                async def send_coap():
                    context = await aiocoap.Context.create_client_context()
                    payload_json = json.dumps(payload if not is_binary else {"binary": payload.hex()})
                    request = aiocoap.Message(code=aiocoap.POST, payload=payload_json.encode())
                    request.set_request_uri(coap_uri)
                    response = await context.request(request).response
                    logger.info("✓ Sent via CoAP: %s", coap_uri)
                    return response
                asyncio.run(send_coap())
            except Exception as coap_exc:
                logger.warning("✗ CoAP send failed: %s", coap_exc)

        if is_binary:
            resp = requests.post(
                server_url,
                data=payload,
                timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/octet-stream"},
            )
            resp.raise_for_status()
            logger.info("✓ Sent BINARY payload → HTTP %d", resp.status_code)
            return True
        else:
            resp = requests.post(
                server_url,
                json=[payload], # FastAPI expects a List
                timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )

            resp.raise_for_status()
            logger.info("✓ Sent JSON %s → HTTP %d", payload.get("species"), resp.status_code)
            return True
    except requests.RequestException as exc:
        logger.warning("✗ Send failed — buffering locally: %s", exc)
        buffer.save(payload if not is_binary else {"binary": payload.hex()})
        return False


def flush_buffer(buffer: LocalBuffer, server_url: str) -> None:
    """Flush all pending locally-buffered records to the server."""
    pending = buffer.count("pending")
    if pending == 0:
        return
    logger.info("Flushing %d buffered record(s) …", pending)
    sent = buffer.flush(server_url)
    logger.info("Flushed %d/%d buffered record(s).", sent, pending)


# ---------------------------------------------------------------------------
# Per-file processing pipeline
# ---------------------------------------------------------------------------


def process_wav_file(
    wav_path: Path,
    server_url: str,
    buffer: LocalBuffer,
    confidence_threshold: float,
    device_id: str,
    demo: bool,
    mqtt_client: Any = None,
    mqtt_topic: str = "echosense/detections",
    coap_uri: str = None,
) -> dict:
    """
    Run the full pipeline (VAD → BirdNET / demo → filter → send) for one file.

    Returns a summary dict with ``{"file", "vad_pass", "detections", "sent", "buffered"}``.
    """
    logger.info("Processing %s …", wav_path.name)
    summary: Dict[str, Any] = {
        "file": wav_path.name,
        "vad_pass": None,
        "detections": 0,
        "sent": 0,
        "buffered": 0,
    }

    # 1. VAD
    global capture_window_sec, silence_discard_sec
    duration_sec = 3.0 # Assume EXACT 3-second windows for demo/files
    if wav_path.name.endswith('.wav'):
        try:
            with wave.open(str(wav_path), "rb") as wf:
                duration_sec = wf.getnframes() / float(wf.getframerate())
        except:
            pass
            
    capture_window_sec += duration_sec
    
    if not demo:
        vad_pass = run_vad(wav_path)
        summary["vad_pass"] = vad_pass
        if not vad_pass:
            logger.info("  VAD: no significant audio in %s — skipping.", wav_path.name)
            silence_discard_sec += duration_sec
            _check_vad_log()
            return summary
    else:
        summary["vad_pass"] = True

    _check_vad_log()

    # 2. BirdNET / fake detections
    t0 = time.monotonic()
    if demo:
        raw_detections = generate_fake_detections(wav_path)
        # EXACT 3-second windows enforced mathematically
        for d in raw_detections:
            d["end_time"] = d["start_time"] + 3.0
        logger.info("  Demo: generated %d fake detection(s).", len(raw_detections))
    else:
        raw_detections = run_birdnet(wav_path)
        logger.info("  BirdNET: found %d detection(s) before threshold.", len(raw_detections))
    t1 = time.monotonic()
    consume_power(150.0, t1 - t0) # Subtract 150mA/sec during BirdNET inference

    # 3. Confidence filter
    filtered = [
        d for d in raw_detections if d.get("confidence", 0.0) >= confidence_threshold
    ]
    logger.info(
        "  After threshold (≥%.2f): %d detection(s) kept.",
        confidence_threshold,
        len(filtered),
    )
    summary["detections"] = len(filtered)

    # 4. Send each detection
    low_bandwidth = os.environ.get("LOW_BANDWIDTH", "0") == "1"
    for det in filtered:
        if low_bandwidth:
            payload = build_binary_payload(det, device_id)
            binary_url = server_url.replace("/api/detections", "/api/ingest/binary")
            ok = send_detection(payload, binary_url, buffer, is_binary=True, mqtt_client=mqtt_client, mqtt_topic=mqtt_topic, coap_uri=coap_uri)
        else:
            payload = build_payload(det, wav_path, device_id)
            ok = send_detection(payload, server_url, buffer, mqtt_client=mqtt_client, mqtt_topic=mqtt_topic, coap_uri=coap_uri)
            
        if ok:
            summary["sent"] += 1
        else:
            summary["buffered"] += 1


    # 5. Flush the local buffer after every file
    flush_buffer(buffer, server_url)

    return summary


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_simulator(args: argparse.Namespace) -> None:
    """Main processing loop — runs once per invocation (or loops with --watch)."""

    buffer = LocalBuffer()
    server_url: str = args.server
    confidence_threshold: float = args.confidence
    device_id: str = args.device_id
    demo: bool = args.demo
    sleep_seconds: int = args.sleep

    # MQTT client initialization
    mqtt_client = None
    mqtt_topic = "echosense/detections"
    if args.mqtt:
        if not MQTT_AVAILABLE:
            logger.warning("MQTT requested but paho-mqtt not installed. Install with: pip install paho-mqtt")
        else:
            mqtt_client = mqtt.Client()
            mqtt_client.connect(args.mqtt_broker, args.mqtt_port, 60)
            mqtt_client.loop_start()
            mqtt_topic = args.mqtt_topic
            logger.info("MQTT enabled: broker=%s:%d, topic=%s", args.mqtt_broker, args.mqtt_port, mqtt_topic)

    # Mesh network initialization
    mesh_network = None
    if args.mesh:
        try:
            from mesh import MeshNetwork
            mesh_network = MeshNetwork(device_id=device_id, listen_port=args.mesh_port)
            mesh_network.start()
            logger.info("Mesh networking enabled on port %d", args.mesh_port)
        except ImportError:
            logger.warning("Mesh networking requested but mesh module not available")
        except Exception as e:
            logger.error("Failed to initialize mesh network: %s", e)

    # TTN integration (uses MQTT)
    if args.ttn:
        if not MQTT_AVAILABLE:
            logger.warning("TTN requested but paho-mqtt not installed. Install with: pip install paho-mqtt")
        elif not args.ttn_app_id or not args.ttn_access_key:
            logger.warning("TTN requested but --ttn-app-id and --ttn-access-key are required")
        else:
            # TTN MQTT broker format: <region>.thethings.network
            ttn_broker = f"{args.ttn_region}.thethings.network"
            ttn_port = 1883
            ttn_topic = f"v3/{args.ttn_app_id}@{args.ttn_region}/devices/+/up"
            mqtt_client = mqtt.Client()
            mqtt_client.username_pw_set(args.ttn_app_id, args.ttn_access_key)
            mqtt_client.connect(ttn_broker, ttn_port, 60)
            mqtt_client.loop_start()
            mqtt_topic = ttn_topic
            logger.info("TTN enabled: region=%s, app_id=%s, topic=%s", args.ttn_region, args.ttn_app_id, ttn_topic)

    # CoAP URI
    coap_uri = None
    if args.coap:
        if not COAP_AVAILABLE:
            logger.warning("CoAP requested but aiocoap not installed. Install with: pip install aiocoap")
        else:
            coap_uri = f"coap://{args.coap_host}:{args.coap_port}/api/detections"
            logger.info("CoAP enabled: %s", coap_uri)

    logger.info("=" * 60)
    logger.info("Edge Simulator starting")
    logger.info("  Server          : %s", server_url)
    logger.info("  Confidence ≥    : %.2f", confidence_threshold)
    logger.info("  Device ID       : %s", device_id)
    logger.info("  Demo mode       : %s", demo)
    logger.info("  Sleep           : %ds between loops", sleep_seconds)
    if args.mqtt:
        logger.info("  MQTT            : enabled (broker=%s:%d)", args.mqtt_broker, args.mqtt_port)
    if args.coap:
        logger.info("  CoAP            : enabled (%s)", coap_uri)
    logger.info("=" * 60)

    # Enable demo time acceleration if in demo mode
    global _demo_time_acceleration_enabled, _demo_simulation_time
    if demo:
        _demo_time_acceleration_enabled = True
        logger.info("  Time acceleration: 1 hour = 5 seconds (720x speed)")

    while True:
        loop_start = time.monotonic()

        if demo:
            # In demo mode produce a batch of fake files to simulate activity
            # Randomly choose 1-2 files to slow down data accumulation
            num_files = random.randint(1, 2)
            demo_files = [Path(f"demo_{i:03d}.wav") for i in range(1, num_files + 1)]
            wav_files = demo_files
            logger.info("[DEMO] Simulating %d fake audio file(s).", len(wav_files))
        else:
            audio_dir = Path(args.audio_dir)
            if not audio_dir.exists():
                logger.error("Audio directory does not exist: %s", audio_dir)
                wav_files = []
            else:
                wav_files = sorted(audio_dir.glob("*.wav"))
                logger.info(
                    "Found %d .wav file(s) in %s", len(wav_files), audio_dir
                )

        total_sent = 0
        total_buffered = 0

        for wav_path in wav_files:
            try:
                summary = process_wav_file(
                    wav_path=wav_path,
                    server_url=server_url,
                    buffer=buffer,
                    confidence_threshold=confidence_threshold,
                    device_id=device_id,
                    demo=demo,
                    mqtt_client=mqtt_client,
                    mqtt_topic=mqtt_topic,
                    coap_uri=coap_uri,
                )
                total_sent += summary["sent"]
                total_buffered += summary["buffered"]
                
                # Move processed file to processed/ directory (only in non-demo mode)
                if not demo:
                    processed_dir = audio_dir / "processed"
                    processed_dir.mkdir(exist_ok=True)
                    try:
                        wav_path.rename(processed_dir / wav_path.name)
                        logger.debug("Moved %s to processed/", wav_path.name)
                    except Exception as e:
                        logger.warning("Failed to move %s: %s", wav_path.name, e)
            except Exception as exc:
                logger.error("Unhandled error for %s: %s", wav_path, exc, exc_info=True)

        elapsed = time.monotonic() - loop_start
        logger.info(
            "Loop done in %.1fs — sent=%d buffered=%d  |  sleeping %ds …",
            elapsed, total_sent, total_buffered, sleep_seconds,
        )

        if not args.watch:
            break

        time.sleep(sleep_seconds)
        consume_power(0.01, sleep_seconds) # Subtract 0.01mA/sec during idle
        
        # Increment simulation time by 1 hour (3600s) every 5-second loop in demo mode
        if _demo_time_acceleration_enabled:
            _demo_simulation_time += 3600  # Advance 1 hour in simulation time



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulator",
        description=(
            "Edge audio simulator: load WAV files → VAD → BirdNET → "
            "filter by confidence → POST to server (LocalBuffer fallback)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--audio-dir",
        default=str(DEFAULT_AUDIO_DIR),
        metavar="DIR",
        help="Directory containing .wav files to process.",
    )
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER_URL,
        metavar="URL",
        help="HTTP endpoint to POST detections to.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=DEFAULT_CONFIDENCE,
        metavar="FLOAT",
        help="Minimum BirdNET confidence score to keep a detection (0–1).",
    )
    parser.add_argument(
        "--device-id",
        default=os.environ.get("EDGE_DEVICE_ID", "edge-device-001"),
        metavar="ID",
        help="Unique identifier for this edge device (can also be set via EDGE_DEVICE_ID env var).",
    )
    parser.add_argument(
        "--sleep",
        type=int,
        default=DEFAULT_SLEEP,
        metavar="SECONDS",
        help="Seconds to sleep between processing loops (only relevant with --watch).",
    )
    parser.add_argument(
        "--lat",
        type=float,
        default=float(os.environ.get("EDGE_LAT", 0.0)),
        help="Lattitude coordinate of this device.",
    )
    parser.add_argument(
        "--lng",
        type=float,
        default=float(os.environ.get("EDGE_LNG", 0.0)),
        help="Longitude coordinate of this device.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        default=False,
        help=(
            "Keep running and re-process the audio directory every --sleep seconds. "
            "Without this flag the simulator runs once and exits."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help=(
            "Demo mode: generate fake detections without reading real WAV files. "
            "Useful for testing the server / buffer integration."
        ),
    )
    parser.add_argument(
        "--low-bandwidth",
        action="store_true",
        default=False,
        help=("Enable Low-Bandwidth Mode (22-byte packing)"),
    )
    parser.add_argument(
        "--edge-inference",
        action="store_true",
        default=False,
        help=("Enable edge inference mode (run classification locally on device)"),
    )
    parser.add_argument(
        "--mqtt",
        action="store_true",
        default=False,
        help=("Enable MQTT transmission mode"),
    )
    parser.add_argument(
        "--mqtt-broker",
        default="localhost",
        metavar="HOST",
        help=("MQTT broker host"),
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=1883,
        metavar="PORT",
        help=("MQTT broker port"),
    )
    parser.add_argument(
        "--mqtt-topic",
        default="echosense/detections",
        metavar="TOPIC",
        help=("MQTT topic for detections"),
    )
    parser.add_argument(
        "--coap",
        action="store_true",
        default=False,
        help=("Enable CoAP transmission mode"),
    )
    parser.add_argument(
        "--coap-host",
        default="localhost",
        metavar="HOST",
        help=("CoAP server host"),
    )
    parser.add_argument(
        "--coap-port",
        type=int,
        default=5683,
        metavar="PORT",
        help=("CoAP server port"),
    )
    parser.add_argument(
        "--ttn",
        action="store_true",
        default=False,
        help=("Enable LoRaWAN TTN integration"),
    )
    parser.add_argument(
        "--ttn-app-id",
        metavar="APP_ID",
        help=("TTN Application ID"),
    )
    parser.add_argument(
        "--ttn-access-key",
        metavar="ACCESS_KEY",
        help=("TTN Access Key"),
    )
    parser.add_argument(
        "--ttn-region",
        default="eu1",
        metavar="REGION",
        help=("TTN region (e.g., eu1, us1, au1)"),
    )

    parser.add_argument(
        "--vad-aggressiveness",
        type=int,
        default=2,
        choices=[0, 1, 2, 3],
        metavar="{0,1,2,3}",
        help="webrtcvad aggressiveness level (0 = least aggressive, 3 = most).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    parser.add_argument(
        "--mesh",
        action="store_true",
        help="Enable mesh networking mode for peer-to-peer device communication.",
    )
    parser.add_argument(
        "--mesh-port",
        type=int,
        default=9000,
        help="UDP port for mesh networking communication.",
    )

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # Apply log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    try:
        import os
        if args.low_bandwidth:
            os.environ["LOW_BANDWIDTH"] = "1"
        
        # Inject coordinates into env for payload builders
        os.environ["EDGE_LAT"] = str(args.lat)
        os.environ["EDGE_LNG"] = str(args.lng)
        
        run_simulator(args)
    except KeyboardInterrupt:
        logger.info("Simulator stopped by user.")


if __name__ == "__main__":
    main()
