#!/usr/bin/env python3
"""
fch-node Flask Dashboard – IP-based monitoring for the local solo pool
"""

import time
import json
import yaml
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request
from datetime import datetime

app = Flask(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.example.yaml"

with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

MODE = CONFIG.get("mode", "solo").upper()
WALLET = CONFIG["wallet"]["address"]
LAZY = CONFIG.get("lazy_mining", {})
FCH_TO_DOGE = float(LAZY.get("fch_to_doge_rate", 0.0015))
DASH_HOST = CONFIG["dashboard"]["host"]
DASH_PORT = int(CONFIG["dashboard"]["port"])

def load_stats():
    stats_file = Path(__file__).resolve().parent.parent / "logs" / "stats.json"
    default = {
        "mode": MODE,
        "wallet": WALLET,
        "hashrate_ths": 0.0,
        "workers": 0,
        "valid_shares": 0,
        "total_shares": 0,
        "invalid_shares": 0,
        "blocks_found": 0,
        "uptime_seconds": 0,
        "fch_to_doge_rate": FCH_TO_DOGE,
        "estimated_fch_day": 0.0,
        "estimated_doge_day": 0.0,
        "worker_details": {},
        "last_block_time": None,
    }
    if stats_file.exists():
        try:
            with open(stats_file, encoding="utf-8") as f:
                data = json.load(f)
                default.update(data)
        except Exception:
            pass

    hr = default.get("hashrate_ths", 0) or 0
    default["estimated_fch_day"] = round(hr * 0.8, 4)
    default["estimated_doge_day"] = round(default["estimated_fch_day"] * FCH_TO_DOGE, 6)
    return default

HTML = """
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fch-node • Solo Pool</title>
<style>
:root{--bg:#0b1220;--card:#141c2f;--accent:#38bdf8;--green:#4ade80;--red:#f87171;--muted:#94a3b8;--text:#e2e8f0}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:1.5rem}
.header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;margin-bottom:2rem}
h1{font-size:1.75rem;background:linear-gradient(90deg,#38bdf8,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.badge{background:var(--card);border:1px solid #334155;padding:.35rem .85rem;border-radius:999px;font-size:.8rem}
.badge.solo{border-color:var(--green);color:var(--green)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.5rem}
.card{background:var(--card);border:1px solid #334155;border-radius:12px;padding:1.25rem}
.card h3{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:.4rem}
.card .val{font-size:1.6rem;font-weight:700}
.val.green{color:var(--green)}.val.blue{color:var(--accent)}.val.red{color:var(--red)}
.sub{font-size:.85rem;color:var(--muted);margin-top:.25rem}
.section{background:var(--card);border:1px solid #334155;border-radius:12px;padding:1.25rem;margin-bottom:1.5rem}
.section h2{font-size:1.1rem;color:var(--accent);margin-bottom:.75rem}
code{background:#0b1220;padding:.6rem 1rem;border-radius:8px;display:inline-block;font-size:1rem}
.footer{text-align:center;color:var(--muted);font-size:.8rem;margin-top:2rem}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{text-align:left;padding:.55rem .4rem;border-bottom:1px solid #334155}
th{color:var(--muted);font-weight:500}
</style>
</head>
<body>
<div class="header">
  <h1>fch-node Solo Pool</h1>
  <div>
    <span class="badge solo">{{ mode }}</span>
    <span class="badge">IP-only • Local</span>
  </div>
</div>

<div class="grid">
  <div class="card"><h3>Hashrate</h3><div class="val blue">{{ "%.4f"|format(s.hashrate_ths) }} TH/s</div><div class="sub">NerdQaxe++ ready</div></div>
  <div class="card"><h3>Valid Shares</h3><div class="val green">{{ s.valid_shares }}</div><div class="sub">Total {{ s.total_shares }} / Invalid {{ s.invalid_shares }}</div></div>
  <div class="card"><h3>Blocks Found</h3><div class="val">{{ s.blocks_found }}</div><div class="sub">Real SOLO</div></div>
  <div class="card"><h3>Uptime</h3><div class="val">{{ uptime }}</div><div class="sub">Workers online: {{ s.workers }}</div></div>
</div>

<div class="grid">
  <div class="card"><h3>Est. FCH / day</h3><div class="val">{{ "%.4f"|format(s.estimated_fch_day) }}</div><div class="sub">Rough estimate</div></div>
  <div class="card"><h3>Est. DOGE / day</h3><div class="val green">{{ "%.6f"|format(s.estimated_doge_day) }}</div><div class="sub">1 FCH = {{ s.fch_to_doge_rate }} DOGE</div></div>
  <div class="card"><h3>Wallet</h3><div class="val" style="font-size:.95rem;word-break:break-all">{{ s.wallet }}</div><div class="sub">Coinbase / default</div></div>
</div>

<div class="section">
  <h2>Miner Connection (NerdQaxe++)</h2>
  <p style="color:var(--muted);margin-bottom:.6rem">Stratum URL (local network only):</p>
  <code>stratum+tcp://{{ ip }}:3333</code>
  <p style="margin-top:.9rem;color:var(--muted);font-size:.9rem">
    Username: <strong>your_FCH_address</strong> &nbsp;•&nbsp; Password: <strong>x</strong> or <strong>d=1000</strong>
  </p>
</div>

{% if s.worker_details %}
<div class="section">
  <h2>Workers</h2>
  <table>
    <tr><th>Name</th><th>Valid</th><th>Hashrate</th><th>Diff</th></tr>
    {% for name, w in s.worker_details.items() %}
    <tr>
      <td>{{ name }}</td>
      <td>{{ w.valid }}</td>
      <td>{{ w.hashrate_ths }} TH/s</td>
      <td>{{ w.difficulty }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endif %}

<div class="footer">
  fch-node • Production Solo • {{ now }}
  <br>Auto-refresh 12s
</div>
<script>setTimeout(()=>location.reload(),12000)</script>
</body>
</html>
"""

@app.route("/")
def index():
    s = load_stats()
    up = s.get("uptime_seconds", 0)
    uptime = f"{up//3600}h {(up%3600)//60}m"
    ip = request.host.split(":")[0]
    return render_template_string(HTML, s=s, mode=s.get("mode", MODE), uptime=uptime, ip=ip, now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.route("/api/stats")
def api_stats():
    return jsonify(load_stats())

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "mode": MODE})

if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    print(f"Dashboard → http://0.0.0.0:{DASH_PORT}")
    print(f"Open in LAN: http://YOUR_IP:{DASH_PORT}")
    app.run(host=DASH_HOST, port=DASH_PORT, debug=False)
