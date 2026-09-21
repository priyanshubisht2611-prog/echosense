import struct
from datetime import datetime, timezone

# Species lookup table (Nainital region)
# Must stay in sync with edge/simulator.py
SPECIES_LOOKUP = {
    0:  "Pycnonotus leucogenys",      # Himalayan Bulbul
    1:  "Urocissa erythroryncha",     # Red-billed Blue Magpie
    2:  "Eumyias thalassinus",        # Verditer Flycatcher
    3:  "Turdus boulboul",            # Grey-winged Blackbird
    4:  "Lophura leucomelanos",       # Kalij Pheasant
    5:  "Phoenicurus leucocephalus",  # White-capped Water Redstart
    6:  "Phoenicurus fuliginosus",    # Plumbeous Water Redstart
    7:  "Garrulax albogularis",       # White-throated Laughingthrush
    8:  "Heterophasia capistrata",    # Rufous Sibia
    9:  "Myophonus caeruleus",         # Blue Whistling Thrush
    10: "Spilopelia chinensis",       # Spotted Dove
    11: "Streptopelia orientalis",    # Oriental Turtle Dove
    12: "Spilornis cheela",           # Crested Serpent Eagle
    13: "Dendrocoptes auriceps",      # Brown-fronted Woodpecker
    14: "Yuhina gularis",             # Stripe-throated Yuhina
    15: "Nucifraga caryocatactes",    # Himalayan Nutcracker
    16: "Carpodacus erythrinus",      # Common Rosefinch
    17: "Phylloscopus xanthoschistos",# Grey-hooded Warbler
    18: "Niltava sundara",            # Rufous-bellied Niltava
    19: "Ficedula superciliaris",     # Ultramarine Flycatcher
}

def parse_binary_payload(blob: bytes):
    if len(blob) != 22:
        raise ValueError(f"Expected 22 bytes, got {len(blob)}")
    
    # Protocol: >4s I H B f f B b x
    # 4s: device_id (truncated to 4 bytes for LoRa efficiency)
    unpacked = struct.unpack('>4s I H B f f B b x', blob)
    device_id_bytes, ts, species_idx, conf, lat, lng, bat, temp = unpacked
    
    device_id = device_id_bytes.decode('utf-8', errors='ignore').strip('\x00')
    species = SPECIES_LOOKUP.get(species_idx, "Unknown")
    confidence = conf / 100.0
    timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
    
    return {
        "device_id": device_id,
        "timestamp": timestamp,
        "species": species,
        "confidence": confidence,
        "latitude": float(lat),
        "longitude": float(lng),
        "battery_pct": int(bat),
        "temp_c": int(temp)
    }
