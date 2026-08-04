#!/usr/bin/env python3
"""BCH2 Solo Mining Dashboard – Mining-Dutch Style"""

from flask import Flask, render_template_string, jsonify
import yaml, json, requests, time
from requests.auth import HTTPBasicAuth
from pathlib import Path

app = Flask(__name__)
ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = ROOT / "config" / "config.example.yaml"
with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)
RPC_HOST, RPC_PORT = cfg["rpc"]["host"], cfg["rpc"]["port"]
RPC_USER, RPC_PASS = cfg["rpc"]["user"], cfg["rpc"]["password"]
PAYOUT_ADDRESS = cfg["pool"]["payout_address"]
STATS_PATH = ROOT / "data" / "stats.json"
PAYOUT_THRESHOLD = float(cfg.get("pool", {}).get("payout_threshold", 50.0))

def rpc(method, params=None):
    try:
        r = requests.post(f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "m", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=10)
        return r.json().get("result")
    except Exception:
        return None

def load_stats():
    try:
        if STATS_PATH.exists():
            return json.loads(STATS_PATH.read_text())
    except Exception:
        pass
    return {"shares_ok": 0, "shares_bad": 0, "blocks_found": 0, "best_share_diff": 0,
            "block_rewards_total": 0.0, "workers": {}, "last_share_time": None,
            "last_share_diff": None, "last_share_hash": None, "started_at": None}

def estimate_hashrate(stats, share_diff):
    ok = stats.get("shares_ok") or 0
    if ok < 2 or not share_diff:
        return None
    started = stats.get("started_at")
    if not started:
        return None
    try:
        t0 = time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S"))
        elapsed = max(time.time() - t0, 1)
        return (ok * float(share_diff) * (2**32)) / elapsed
    except Exception:
        return None

def fmt_hashrate(hps):
    if hps is None:
        return "–"
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s"]
    i = 0
    while hps >= 1000 and i < len(units) - 1:
        hps /= 1000; i += 1
    return f"{hps:.2f} {units[i]}"

def fmt_diff(d):
    if d is None: return "–"
    if d >= 1e9: return f"{d/1e9:.2f} G"
    if d >= 1e6: return f"{d/1e6:.2f} M"
    if d >= 1e3: return f"{d/1e3:.2f} k"
    return f"{d:.2f}"

def eta_seconds(network_diff, hashrate):
    if not network_diff or not hashrate or hashrate <= 0:
        return None
    return (network_diff * (2**32)) / hashrate

def fmt_duration(sec):
    if sec is None or sec < 0: return "∞"
    if sec < 60: return f"{int(sec)}s"
    if sec < 3600: return f"{int(sec//60)}m {int(sec%60)}s"
    if sec < 86400: return f"{int(sec//3600)}h {int((sec%3600)//60)}m"
    return f"{int(sec//86400)}d {int((sec%86400)//3600)}h"

HTML = open(__file__).read()  # placeholder replaced below
