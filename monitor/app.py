#!/usr/bin/env python3
"""
BCH2 Solo Mining Dashboard
Nur über lokale IP erreichbar
"""

from flask import Flask, render_template_string, jsonify
import yaml
import requests
from requests.auth import HTTPBasicAuth
from pathlib import Path
import time

app = Flask(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.example.yaml"

with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

RPC_HOST = cfg["rpc"]["host"]
RPC_PORT = cfg["rpc"]["port"]
RPC_USER = cfg["rpc"]["user"]
RPC_PASS = cfg["rpc"]["password"]
PAYOUT_ADDRESS = cfg["pool"]["payout_address"]

def rpc(method, params=None):
    if params is None:
        params = []
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "monitor", "method": method, "params": params},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS),
            timeout=10
        )
        data = r.json()
        return data.get("result")
    except Exception:
        return None

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BCH2 Solo Node</title>
    <style>
        :root { --bg: #0f1115; --card: #1a1d24; --text: #e0e0e0; --accent: #3ecf8e; --muted: #888; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 2rem; }
        h1 { margin-bottom: 0.5rem; }
        .subtitle { color: var(--muted); margin-bottom: 2rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; }
        .card { background: var(--card); border-radius: 12px; padding: 1.25rem; }
        .card h3 { font-size: 0.85rem; color: var(--muted); margin-bottom: 0.4rem; }
        .card .value { font-size: 1.6rem; font-weight: 600; color: var(--accent); }
        .status-ok { color: #3ecf8e; }
        .status-bad { color: #ff6b6b; }
        footer { margin-top: 3rem; color: var(--muted); font-size: 0.85rem; }
    </style>
</head>
<body>
    <h1>BCH2 Solo Node</h1>
    <p class="subtitle">Lokales Solo-Mining • Nur du</p>

    <div class="grid">
        <div class="card">
            <h3>Node Status</h3>
            <div class="value {{ 'status-ok' if synced else 'status-bad' }}">
                {{ 'Synced' if synced else 'Syncing...' }}
            </div>
        </div>
        <div class="card">
            <h3>Block Height</h3>
            <div class="value">{{ height or '–' }}</div>
        </div>
        <div class="card">
            <h3>Difficulty</h3>
            <div class="value">{{ difficulty or '–' }}</div>
        </div>
        <div class="card">
            <h3>Connections</h3>
            <div class="value">{{ connections or 0 }}</div>
        </div>
        <div class="card">
            <h3>Wallet Balance</h3>
            <div class="value">{{ '%.4f'|format(balance) if balance is not none else '–' }} BCH2</div>
        </div>
        <div class="card">
            <h3>Payout Address</h3>
            <div class="value" style="font-size:0.95rem; word-break:break-all;">{{ payout }}</div>
        </div>
    </div>

    <footer>
        Aktualisiert: {{ now }} • Stratum Port 3333 • Dashboard nur lokal
    </footer>

    <script>
        setTimeout(() => location.reload(), 15000);
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    info = rpc("getblockchaininfo") or {}
    net = rpc("getnetworkinfo") or {}
    balance = rpc("getbalance")
    height = info.get("blocks")
    difficulty = info.get("difficulty")
    synced = not info.get("initialblockdownload", True)
    connections = net.get("connections", 0)

    return render_template_string(
        DASHBOARD_HTML,
        synced=synced,
        height=height,
        difficulty=f"{difficulty:,.0f}" if difficulty else None,
        connections=connections,
        balance=balance,
        payout=PAYOUT_ADDRESS,
        now=time.strftime("%Y-%m-%d %H:%M:%S")
    )

@app.route("/api/status")
def api_status():
    info = rpc("getblockchaininfo") or {}
    balance = rpc("getbalance")
    return jsonify({
        "synced": not info.get("initialblockdownload", True),
        "height": info.get("blocks"),
        "difficulty": info.get("difficulty"),
        "balance": balance,
        "payout_address": PAYOUT_ADDRESS
    })

if __name__ == "__main__":
    host = cfg.get("monitor", {}).get("host", "0.0.0.0")
    port = cfg.get("monitor", {}).get("port", 5000)
    app.run(host=host, port=port, debug=False)
