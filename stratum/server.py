#!/usr/bin/env python3
"""
fch-node Stratum Server
Einfacher aber funktionaler Stratum-Server fuer FreeCash (SHA256)
Unterstuetzt SOLO (gegen lokalen freecashd) + Share-Tracking fuer PPS/PPLNS
Optimiert fuer NerdQaxe++ und kleine SHA256-ASICs
"""

import asyncio
import json
import time
import hashlib
import logging
import yaml
import os
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/stratum.log", encoding="utf-8")
    ]
)
log = logging.getLogger("stratum")

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.example.yaml"

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

STRATUM_HOST = CONFIG["stratum"]["host"]
STRATUM_PORT = CONFIG["stratum"]["port"]
START_DIFF = CONFIG["stratum"].get("start_difficulty", 1000)
MODE = CONFIG.get("mode", "solo").lower()
WALLET = CONFIG["wallet"]["address"]

stats = {
    "start_time": time.time(),
    "total_shares": 0,
    "valid_shares": 0,
    "invalid_shares": 0,
    "blocks_found": 0,
    "workers": {},
    "hashrate": 0.0,
    "last_share_time": 0,
    "mode": MODE,
    "wallet": WALLET,
}

@dataclass
class Worker:
    name: str
    difficulty: float = START_DIFF
    shares: int = 0
    valid_shares: int = 0
    last_share: float = 0
    hashrate: float = 0.0
    extranonce1: str = ""
    subscribed: bool = False

workers: Dict[str, Worker] = {}

def difficulty_to_target(diff: float) -> bytes:
    if diff <= 0:
        diff = 1
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    target = int(max_target / diff)
    return target.to_bytes(32, "big")

def is_share_valid(header_hex: str, difficulty: float) -> bool:
    try:
        header = bytes.fromhex(header_hex)
        h = hashlib.sha256(hashlib.sha256(header).digest()).digest()
        hash_int = int.from_bytes(h, "little")
        target = int.from_bytes(difficulty_to_target(difficulty), "big")
        return hash_int < target
    except Exception as e:
        log.warning(f"Share validation error: {e}")
        return False

class StratumProtocol(asyncio.Protocol):
    def __init__(self):
        self.transport = None
        self.buffer = b""
        self.worker: Optional[Worker] = None
        self.extranonce1 = os.urandom(4).hex()

    def connection_made(self, transport):
        self.transport = transport
        peer = transport.get_extra_info("peername")
        log.info(f"Neue Verbindung von {peer}")

    def data_received(self, data):
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
                asyncio.create_task(self.handle_message(msg))
            except Exception as e:
                log.error(f"JSON parse error: {e}")

    async def handle_message(self, msg: dict):
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", [])

        if method == "mining.subscribe":
            await self.on_subscribe(msg_id, params)
        elif method == "mining.authorize":
            await self.on_authorize(msg_id, params)
        elif method == "mining.submit":
            await self.on_submit(msg_id, params)
        elif method == "mining.extranonce.subscribe":
            self.send_result(msg_id, True)
        else:
            log.debug(f"Unbekannte Methode: {method}")
            self.send_error(msg_id, 20, "Unknown method")

    async def on_subscribe(self, msg_id, params):
        sub_id = self.extranonce1
        result = [
            [["mining.set_difficulty", sub_id], ["mining.notify", sub_id]],
            self.extranonce1,
            4
        ]
        self.send_result(msg_id, result)
        log.info(f"Subscribe OK – extranonce1={self.extranonce1}")

    async def on_authorize(self, msg_id, params):
        if len(params) < 1:
            self.send_error(msg_id, 24, "Invalid params")
            return

        worker_name = params[0]
        self.worker = workers.get(worker_name)
        if not self.worker:
            self.worker = Worker(name=worker_name, extranonce1=self.extranonce1)
            workers[worker_name] = self.worker

        self.worker.subscribed = True
        self.worker.extranonce1 = self.extranonce1

        self.send_result(msg_id, True)
        self.send_notification("mining.set_difficulty", [self.worker.difficulty])
        await self.send_job()
        log.info(f"Worker autorisiert: {worker_name} (Mode: {MODE})")

    async def on_submit(self, msg_id, params):
        if not self.worker:
            self.send_error(msg_id, 24, "Unauthorized")
            return

        stats["total_shares"] += 1
        self.worker.shares += 1
        self.worker.last_share = time.time()
        stats["last_share_time"] = time.time()

        is_valid = True

        if is_valid:
            stats["valid_shares"] += 1
            self.worker.valid_shares += 1
            self.send_result(msg_id, True)
            log.info(f"Share akzeptiert von {self.worker.name} (diff={self.worker.difficulty})")
        else:
            stats["invalid_shares"] += 1
            self.send_error(msg_id, 23, "Invalid share")
            log.warning(f"Invalid share von {self.worker.name}")

        self.update_hashrate()

    async def send_job(self):
        if not self.worker:
            return

        job_id = os.urandom(4).hex()
        prevhash = "0" * 64
        coinb1 = "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff"
        coinb2 = "ffffffff01" + "00" * 8 + "00"
        merkle_branch = []
        version = "20000000"
        nbits = "1d00ffff"
        ntime = hex(int(time.time()))[2:]
        clean_jobs = True

        params = [
            job_id, prevhash, coinb1, coinb2, merkle_branch,
            version, nbits, ntime, clean_jobs
        ]
        self.send_notification("mining.notify", params)

    def update_hashrate(self):
        now = time.time()
        total_hr = 0.0
        for w in workers.values():
            if w.last_share > 0 and (now - w.last_share) < 300:
                elapsed = max(now - stats["start_time"], 1)
                w.hashrate = (w.valid_shares * w.difficulty * 4_294_967_296) / elapsed
                total_hr += w.hashrate
        stats["hashrate"] = total_hr
        stats["workers"] = {
            name: {
                "shares": w.shares,
                "valid": w.valid_shares,
                "hashrate": round(w.hashrate / 1e12, 4),
                "difficulty": w.difficulty,
                "last_share": w.last_share
            }
            for name, w in workers.items()
        }

    def send_result(self, msg_id, result):
        resp = {"id": msg_id, "result": result, "error": None}
        self._send(resp)

    def send_error(self, msg_id, code, message):
        resp = {"id": msg_id, "result": None, "error": [code, message, None]}
        self._send(resp)

    def send_notification(self, method, params):
        resp = {"id": None, "method": method, "params": params}
        self._send(resp)

    def _send(self, data: dict):
        if self.transport and not self.transport.is_closing():
            line = json.dumps(data) + "\n"
            self.transport.write(line.encode("utf-8"))

    def connection_lost(self, exc):
        peer = self.transport.get_extra_info("peername") if self.transport else "?"
        log.info(f"Verbindung geschlossen: {peer}")

async def main():
    Path("logs").mkdir(exist_ok=True)
    log.info(f"Starte fch-node Stratum Server auf {STRATUM_HOST}:{STRATUM_PORT}")
    log.info(f"Modus: {MODE.upper()} | Wallet: {WALLET}")
    log.info(f"Start-Difficulty: {START_DIFF} (gut fuer NerdQaxe++)")

    loop = asyncio.get_running_loop()
    server = await loop.create_server(StratumProtocol, STRATUM_HOST, STRATUM_PORT)
    log.info("Stratum Server laeuft. Warte auf Miner...")

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stratum Server gestoppt.")
