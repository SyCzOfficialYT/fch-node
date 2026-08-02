#!/usr/bin/env python3
"""
fch-node Flask Monitoring Dashboard
Erreichbar ueber die IP des Rechners (z.B. http://192.168.1.50:5000)
"""

import time
import yaml
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request
from datetime import datetime

app = Flask(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.example.yaml"

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

MODE = CONFIG.get("mode", "solo").upper()
WALLET = CONFIG["wallet"]["address"]
LAZY = CONFIG.get("lazy_mining", {})
FCH_TO_DOGE = LAZY.get("fch_to_doge_rate", 0.0015)
DASH_HOST = CONFIG["dashboard"]["host"]
DASH_PORT = CONFIG["dashboard"]["port"]

stats = {
    "mode": MODE,
    "wallet": WALLET,
    "hashrate_ths": 0.0,
    "workers": 0,
    "valid_shares": 0,
    "total_shares": 0,
    "blocks_found": 0,
    "uptime_seconds": 0,
    "last_share": None,
    "estimated_fch_day": 0.0,
    "estimated_doge_day": 0.0,
    "fch_to_doge_rate": FCH_TO_DOGE,
    "start_time": time.time(),
}

def update_stats_from_file():
    stats_file = Path(__file__).parent.parent / "logs" / "stats.json"
    if stats_file.exists():
        try:
            import json
            with open(stats_file) as f:
                data = json.load(f)
                stats.update(data)
        except Exception:
            pass

    stats["uptime_seconds"] = int(time.time() - stats["start_time"])

    if stats["hashrate_ths"] > 0:
        stats["estimated_fch_day"] = round(stats["hashrate_ths"] * 0.5, 4)
        stats["estimated_doge_day"] = round(stats["estimated_fch_day"] * FCH_TO_DOGE, 6)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>fch-node Dashboard</title>
    <style>
        :root {
            --bg: #0f172a;
            --card: #1e293b;
            --accent: #38bdf8;
            --green: #4ade80;
            --orange: #fb923c;
            --text: #e2e8f0;
            --muted: #94a3b8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 1.5rem;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            flex-wrap: wrap;
            gap: 1rem;
        }
        h1 {
            font-size: 1.8rem;
            background: linear-gradient(90deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .badge {
            background: var(--card);
            padding: 0.4rem 0.9rem;
            border-radius: 999px;
            font-size: 0.85rem;
            border: 1px solid #334155;
        }
        .badge.solo { border-color: var(--green); color: var(--green); }
        .badge.pps { border-color: var(--orange); color: var(--orange); }
        .badge.pplns { border-color: #c084fc; color: #c084fc; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.2rem;
            margin-bottom: 2rem;
        }
        .card {
            background: var(--card);
            border-radius: 12px;
            padding: 1.4rem;
            border: 1px solid #334155;
        }
        .card h3 {
            font-size: 0.85rem;
            color: var(--muted);
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .card .value {
            font-size: 1.8rem;
            font-weight: 700;
        }
        .card .sub {
            font-size: 0.9rem;
            color: var(--muted);
            margin-top: 0.3rem;
        }
        .value.green { color: var(--green); }
        .value.blue { color: var(--accent); }
        .section {
            background: var(--card);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid #334155;
            margin-bottom: 1.5rem;
        }
        .section h2 {
            font-size: 1.2rem;
            margin-bottom: 1rem;
            color: var(--accent);
        }
        .footer {
            text-align: center;
            color: var(--muted);
            font-size: 0.85rem;
            margin-top: 2rem;
        }
        .refresh { font-size: 0.8rem; color: var(--muted); }
    </style>
</head>
<body>
    <div class="header">
        <h1>fch-node Dashboard</h1>
        <div>
            <span class="badge {{ mode_class }}">{{ mode }}</span>
            <span class="badge">Lokal • IP-basiert</span>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Hashrate</h3>
            <div class="value blue">{{ "%.3f"|format(stats.hashrate_ths) }} TH/s</div>
            <div class="sub">NerdQaxe++ & Co.</div>
        </div>
        <div class="card">
            <h3>Gueltige Shares</h3>
            <div class="value green">{{ stats.valid_shares }}</div>
            <div class="sub">Gesamt: {{ stats.total_shares }}</div>
        </div>
        <div class="card">
            <h3>Bloecke gefunden</h3>
            <div class="value">{{ stats.blocks_found }}</div>
            <div class="sub">SOLO-Modus</div>
        </div>
        <div class="card">
            <h3>Uptime</h3>
            <div class="value">{{ uptime }}</div>
            <div class="sub">Seit Start</div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Geschaetzt FCH / Tag</h3>
            <div class="value">{{ "%.4f"|format(stats.estimated_fch_day) }} FCH</div>
            <div class="sub">Lazy Estimate</div>
        </div>
        <div class="card">
            <h3>Geschaetzt DOGE / Tag</h3>
            <div class="value green">{{ "%.6f"|format(stats.estimated_doge_day) }} DOGE</div>
            <div class="sub">Kurs: 1 FCH = {{ stats.fch_to_doge_rate }} DOGE</div>
        </div>
        <div class="card">
            <h3>Wallet</h3>
            <div class="value" style="font-size:1rem; word-break:break-all;">{{ stats.wallet }}</div>
            <div class="sub">SOLO Coinbase</div>
        </div>
        <div class="card">
            <h3>Aktiver Modus</h3>
            <div class="value">{{ mode }}</div>
            <div class="sub">Aendern in config.yaml</div>
        </div>
    </div>

    <div class="section">
        <h2>Verbindung fuer deinen NerdQaxe++</h2>
        <p style="margin-bottom:0.8rem; color:var(--muted);">
            Stratum URL (nur im lokalen Netz):
        </p>
        <code style="background:#0f172a; padding:0.8rem 1.2rem; border-radius:8px; display:inline-block; font-size:1.1rem;">
            stratum+tcp://{{ request.host.split(':')[0] }}:3333
        </code>
        <p style="margin-top:1rem; color:var(--muted); font-size:0.9rem;">
            Username: <strong>deine_FCH_Adresse</strong> &nbsp;|&nbsp; Password: <strong>x</strong> oder <strong>d=1000</strong>
        </p>
    </div>

    <div class="footer">
        fch-node • Lokaler FreeCash Pool • Aktualisiert: {{ now }}
        <br>
        <span class="refresh">Seite aktualisiert sich alle 15 Sekunden</span>
    </div>

    <script>
        setTimeout(() => location.reload(), 15000);
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    update_stats_from_file()
    uptime_s = stats["uptime_seconds"]
    hours = uptime_s // 3600
    minutes = (uptime_s % 3600) // 60
    uptime_str = f"{hours}h {minutes}m"

    mode_class = stats["mode"].lower()
    return render_template_string(
        HTML_TEMPLATE,
        stats=stats,
        mode=stats["mode"],
        mode_class=mode_class,
        uptime=uptime_str,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        request=request,
    )

@app.route("/api/stats")
def api_stats():
    update_stats_from_file()
    return jsonify(stats)

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "mode": MODE})

if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    print(f"fch-node Dashboard laeuft auf http://0.0.0.0:{DASH_PORT}")
    print(f"Im lokalen Netz erreichbar unter http://DEINE_IP:{DASH_PORT}")
    app.run(host=DASH_HOST, port=DASH_PORT, debug=False)
