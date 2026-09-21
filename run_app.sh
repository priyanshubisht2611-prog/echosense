#!/bin/bash
# =============================================================================
#  EchoSense — Live BirdNET Mode
#  Installs all dependencies, then runs the backend + a real-audio edge
#  simulator that watches edge/recordings/ for .wav files and runs BirdNET.
#
#  Usage:
#    ./run_app.sh
#    ./run_app.sh --device-id SITE-01 --lat 29.3919 --lng 79.4542
# =============================================================================

set -euo pipefail
trap "kill 0" EXIT

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "==========================================="
echo "🦉  EchoSense — Live BirdNET Mode"
echo "==========================================="

# ── [0/3] Python environment & dependencies ───────────────────────────────────
echo ""
echo "[0/3] Setting up Python environment & installing dependencies..."

if [ ! -f "venv/bin/activate" ]; then
    echo "      Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet birdnetlib webrtcvad || \
    echo "      ⚠  birdnetlib/webrtcvad install failed — live analysis unavailable"

echo "      ✓ Dependencies ready"

# ── [1/3] Backend ─────────────────────────────────────────────────────────────
echo ""
echo "[1/3] Wiping database and starting FastAPI backend..."
rm -f data/echosense.db data/echosense.db-shm data/echosense.db-wal
uvicorn backend.main:app --port 8000 > backend.log 2>&1 &
BACKEND_PID=$!
sleep 3

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "      ✗ Backend failed to start — check backend.log:"
    cat backend.log
    exit 1
fi
echo "      ✓ Backend running  →  http://127.0.0.1:8000"

# ── [2/3] Edge simulator (real-audio + BirdNET) ───────────────────────────────
echo ""
echo "[2/3] Starting edge simulator (BirdNET mode)..."
cd edge
mkdir -p recordings

python3 simulator.py --watch "$@" > edge_app.log 2>&1 &
echo "      ✓ Simulator watching  edge/recordings/  for .wav files"
echo "        (logs → edge/edge_app.log)"

# ── Ready ─────────────────────────────────────────────────────────────────────
echo ""
echo "🦉  EchoSense is fully running!"
echo "    Dashboard  →  http://127.0.0.1:8000/dashboard/index.html"
echo ""
echo "    Drop mono 16-bit .wav files into edge/recordings/ to trigger"
echo "    BirdNET analysis and live dashboard updates."
echo ""
echo "    Tip: pass --device-id, --lat, --lng to identify this node:"
echo "      ./run_app.sh --device-id SITE-01 --lat 29.39 --lng 79.45"
echo ""
echo "Press [CTRL+C] to stop all services."

wait
