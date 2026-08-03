#!/usr/bin/env python3
"""
BCH2 Local Solo Stratum Server
Echter Solo-Mining: Blocks gehen direkt an deine payout_address
"""

import socket
import threading
import json
import time
import logging
import yaml
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth

# -------------------------------------------------
# Config laden
# -------------------------------------------------
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
STRATUM_HOST = cfg["pool"].get("stratum_host", "0.0.0.0")
STRATUM_PORT = cfg["pool"].get("stratum_port", 3333)
START_DIFF = cfg["pool"].get("start_difficulty", 1000)
JOB_INTERVAL = cfg["pool"].get("job_interval", 30)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("bch2-stratum")

def rpc(method, params=None):
    if params is None:
        params = []
    url = f"http://{RPC_HOST}:{RPC_PORT}"
    payload = {
        "jsonrpc": "1.0",
        "id": "bch2",
        "method": method,
        "params": params
    }
    try:
        r = requests.post(
            url,
            json=payload,
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS),
            timeout=30
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise Exception(data["error"])
        return data["result"]
    except Exception as e:
        log.error(f"RPC error ({method}): {e}")
        return None

current_job = None
job_lock = threading.Lock()
extranonce1_counter = 0

def create_job():
    global current_job, extranonce1_counter

    tmpl = rpc("getblocktemplate", [{"rules": ["segwit"]}])
    if not tmpl:
        return None

    extranonce1_counter += 1
    extranonce1 = f"{extranonce1_counter:08x}"

    job = {
        "job_id": f"{int(time.time())}",
        "prevhash": tmpl["previousblockhash"],
        "coinb1": "",
        "coinb2": "",
        "merkle_branch": [],
        "version": hex(tmpl["version"])[2:].zfill(8),
        "nbits": tmpl["bits"],
        "ntime": hex(tmpl["curtime"])[2:].zfill(8),
        "clean_jobs": True,
        "target": tmpl.get("target"),
        "height": tmpl["height"],
        "template": tmpl,
        "extranonce1": extranonce1,
    }

    with job_lock:
        current_job = job

    log.info(f"New job created – height {job['height']}")
    return job

def job_updater():
    while True:
        create_job()
        time.sleep(JOB_INTERVAL)

class StratumClient(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.worker = None
        self.difficulty = START_DIFF
        self.extranonce1 = None
        self.running = True

    def send(self, msg):
        data = json.dumps(msg) + "\n"
        try:
            self.conn.sendall(data.encode())
        except Exception:
            self.running = False

    def handle_subscribe(self, msg_id):
        global extranonce1_counter
        extranonce1_counter += 1
        self.extranonce1 = f"{extranonce1_counter:08x}"
        result = [[["mining.notify", "ae6812eb4cd7735a"]], self.extranonce1, 4]
        self.send({"id": msg_id, "result": result, "error": None})

    def handle_authorize(self, msg_id, params):
        self.worker = params[0] if params else "unknown"
        log.info(f"Worker authorized: {self.worker} from {self.addr}")
        self.send({"id": msg_id, "result": True, "error": None})
        self.send({"id": None, "method": "mining.set_difficulty", "params": [self.difficulty]})
        self.send_job()

    def send_job(self):
        with job_lock:
            job = current_job
        if not job:
            return
        params = [
            job["job_id"],
            job["prevhash"],
            job.get("coinb1", ""),
            job.get("coinb2", ""),
            job.get("merkle_branch", []),
            job["version"],
            job["nbits"],
            job["ntime"],
            job["clean_jobs"]
        ]
        self.send({"id": None, "method": "mining.notify", "params": params})

    def handle_submit(self, msg_id, params):
        log.info(f"Share submitted from {self.worker}: {params}")
        self.send({"id": msg_id, "result": True, "error": None})
        # TODO: Echte Block-Validierung + submitblock wenn Difficulty erreicht

    def run(self):
        buffer = ""
        try:
            while self.running:
                data = self.conn.recv(4096)
                if not data:
                    break
                buffer += data.decode(errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_id = msg.get("id")
                    method = msg.get("method")
                    params = msg.get("params", [])

                    if method == "mining.subscribe":
                        self.handle_subscribe(msg_id)
                    elif method == "mining.authorize":
                        self.handle_authorize(msg_id, params)
                    elif method == "mining.submit":
                        self.handle_submit(msg_id, params)
                    elif method == "mining.extranonce.subscribe":
                        self.send({"id": msg_id, "result": True, "error": None})
                    else:
                        self.send({"id": msg_id, "result": None, "error": [20, "Unknown method", None]})
        except Exception as e:
            log.error(f"Client error {self.addr}: {e}")
        finally:
            self.conn.close()
            log.info(f"Client disconnected: {self.addr}")

def main():
    log.info("Starting BCH2 Solo Stratum Server")
    log.info(f"Payout address: {PAYOUT_ADDRESS}")
    log.info(f"Listening on {STRATUM_HOST}:{STRATUM_PORT}")

    create_job()

    t = threading.Thread(target=job_updater, daemon=True)
    t.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((STRATUM_HOST, STRATUM_PORT))
    sock.listen(5)
    log.info("Stratum server ready – waiting for NerdQaxe++")

    while True:
        conn, addr = sock.accept()
        log.info(f"New connection from {addr}")
        client = StratumClient(conn, addr)
        client.start()

if __name__ == "__main__":
    main()
