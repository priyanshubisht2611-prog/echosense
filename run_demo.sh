#!/bin/bash
# =============================================================================
#  EchoSense — Demo Mode (3-node Nainital simulation)
#  Installs all dependencies, resets the DB, registers 3 field nodes around
#  the Nainital / Kumaon Himalaya region, then runs one simulator per node.
# =============================================================================

set -euo pipefail
trap "kill 0" EXIT

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "==========================================="
echo "🦉  EchoSense — Demo Mode (Nainital Region)"
echo "==========================================="

# ── [0/4] Python environment & dependencies ───────────────────────────────────
echo ""
echo "[0/4] Setting up Python environment & installing dependencies..."

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "      Cleaning and creating virtual environment..."
    rm -rf venv
    python3 -m venv venv
fi

if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Upgrade pip and install all requirements
pip install --quiet --upgrade pip setuptools wheel
pip install --quiet -r requirements.txt
# BirdNET + VAD
pip install --quiet birdnetlib webrtcvad || \
    echo "      ⚠  birdnetlib/webrtcvad install failed (demo mode will still work)"

echo "      ✓ Dependencies ready"

# ── [1/4] Reset database ──────────────────────────────────────────────────────
echo ""
echo "[1/4] Resetting database..."
rm -f data/echosense.db
mkdir -p data
echo "      ✓ Fresh database ready"

# ── [2/4] Backend ─────────────────────────────────────────────────────────────
echo ""
echo "[2/4] Starting FastAPI backend..."
uvicorn backend.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
BACKEND_PID=$!
sleep 3

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "      ✗ Backend failed to start — check backend.log:"
    cat backend.log
    exit 1
fi
echo "      ✓ Backend running  →  http://127.0.0.1:8000"

# ── Pre-register nodes with 4-byte compatible IDs (E-NK, E-PG, E-KB) ─────────
echo "      Registering 3 field nodes..."
curl -sf -X POST http://127.0.0.1:8000/api/devices \
  -H "Content-Type: application/json" \
  -d '{"id":"E-NK","site_name":"Nainital Lake Node","lat":29.3919,"lng":79.4542,"battery_pct":95}' \
  > /dev/null && echo "        ✓ E-NK  Nainital Lake Node"

curl -sf -X POST http://127.0.0.1:8000/api/devices \
  -H "Content-Type: application/json" \
  -d '{"id":"E-PG","site_name":"Pangot Forest Node","lat":29.4351,"lng":79.3951,"battery_pct":88}' \
  > /dev/null && echo "        ✓ E-PG  Pangot Forest Node"

curl -sf -X POST http://127.0.0.1:8000/api/devices \
  -H "Content-Type: application/json" \
  -d '{"id":"E-KB","site_name":"Kilbury Reserve Node","lat":29.3726,"lng":79.4231,"battery_pct":92}' \
  > /dev/null && echo "        ✓ E-KB  Kilbury Reserve Node"

# ── [3/4] Edge simulators — one per node ─────────────────────────────────────
echo ""
echo "[3/4] Starting 3 edge simulators (Nainital region)..."
cd edge

# Use 4-byte IDs to avoid binary protocol truncation
python3 simulator.py --demo --low-bandwidth --watch \
    --device-id E-NK --lat 29.3919 --lng 79.4542 \
    > e_nk.log 2>&1 &
echo "      ✓ E-NK  running  (logs → edge/e_nk.log)"

sleep 1

python3 simulator.py --demo --low-bandwidth --watch \
    --device-id E-PG --lat 29.4351 --lng 79.3951 \
    > e_pg.log 2>&1 &
echo "      ✓ E-PG  running  (logs → edge/e_pg.log)"

sleep 1

python3 simulator.py --demo --low-bandwidth --watch \
    --device-id E-KB --lat 29.3726 --lng 79.4231 \
    > e_kb.log 2>&1 &
echo "      ✓ E-KB  running  (logs → edge/e_kb.log)"

# ── Ready ─────────────────────────────────────────────────────────────────────
echo ""
echo "🦉  EchoSense is fully running!"
echo "    Dashboard  →  http://127.0.0.1:8000/dashboard/index.html"
echo ""
echo "    Nodes (Compatibility Mode):"
echo "      E-NK  Nainital Lake Node   29.3919°N 79.4542°E"
echo "      E-PG  Pangot Forest Node   29.4351°N 79.3951°E"
echo "      E-KB  Kilbury Reserve Node 29.3726°N 79.4231°E"
echo ""
echo "Press [CTRL+C] to stop all services."

wait
