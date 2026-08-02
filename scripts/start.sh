#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== fch-node Starter ==="

# Config prüfen
if [ ! -f config/config.yaml ]; then
    echo "Kopiere Beispiel-Config..."
    cp config/config.example.yaml config/config.yaml
    echo "Bitte config/config.yaml anpassen (Wallet, RPC-Passwort etc.)"
    exit 1
fi

mkdir -p logs

# Virtualenv (optional)
if [ ! -d venv ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo "Starte Stratum Server..."
python stratum/server.py &
STRATUM_PID=$!

echo "Starte Dashboard..."
python monitor/app.py &
DASH_PID=$!

echo ""
echo "Stratum  : Port 3333"
echo "Dashboard: http://0.0.0.0:5000  (im lokalen Netz über deine IP)"
echo ""
echo "Beenden mit Ctrl+C"

trap "kill $STRATUM_PID $DASH_PID 2>/dev/null" EXIT
wait
