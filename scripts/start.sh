#!/bin/bash
set -e

echo "=== BCH2 Solo Node Starter ==="

if [ ! -f config/config.yaml ]; then
    echo "Bitte zuerst config/config.yaml anlegen (siehe config.example.yaml)"
    exit 1
fi

echo "Prüfe Node..."
if ! bitcoincashII-cli getblockchaininfo > /dev/null 2>&1; then
    echo "WARNUNG: bitcoincashIId scheint nicht zu laufen oder RPC ist falsch konfiguriert."
    echo "Starte die Node mit: bitcoincashIId -daemon"
fi

echo "Starte Stratum Server..."
python3 -c 'from stratum import server; from stratum.asic_compat import patch; patch(server); server.main()' &
STRATUM_PID=$!

echo "Starte Dashboard..."
python3 monitor/app.py &
MONITOR_PID=$!

echo ""
echo "Stratum läuft (PID $STRATUM_PID) – Port 3333"
echo "Dashboard läuft (PID $MONITOR_PID) – Port 5000"
echo ""
echo "NerdQaxe++ verbinden mit:"
echo "  stratum+tcp://DEINE_IP:3333"
echo ""
echo "Ctrl+C zum Beenden"

trap "kill $STRATUM_PID $MONITOR_PID 2>/dev/null" EXIT
wait
