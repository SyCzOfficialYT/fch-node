#!/usr/bin/env python3
"""
fch-node – Production Solo Stratum Server for FreeCash (FCH)

Real getblocktemplate → job generation → share validation → submitblock
Designed for local / private use with NerdQaxe++ and other SHA256 ASICs.
"""

import asyncio
import json
import time
import hashlib
import struct
import logging
import yaml
import os
import sys
from pathlib import Path
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from binascii import hexlify, unhexlify
import requests
from requests.auth import HTTPBasicAuth

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/stratum.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("fch-stratum")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.example.yaml"

with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

STRATUM_HOST = CONFIG["stratum"]["host"]
STRATUM_PORT = int(CONFIG["stratum"]["port"])
START_DIFF = float(CONFIG["stratum"].get("start_difficulty", 1000))

RPC_HOST = CONFIG["rpc"]["host"]
RPC_PORT = int(CONFIG["rpc"]["port"])
RPC_USER = CONFIG["rpc"]["user"]
RPC_PASS = CONFIG["rpc"]["password"]
RPC_TIMEOUT = int(CONFIG["rpc"].get("timeout", 30))

DEFAULT_WALLET = CONFIG["wallet"]["address"]
MODE = CONFIG.get("mode", "solo").lower()

def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def reverse_hex(h: str) -> str:
    return hexlify(unhexlify(h)[::-1]).decode()

def bits_to_target(bits: str) -> int:
    bits_int = int(bits, 16)
    exp = bits_int >> 24
    mant = bits_int & 0xFFFFFF
    if exp <= 3:
        target = mant >> (8 * (3 - exp))
    else:
        target = mant << (8 * (exp - 3))
    return target

def difficulty_to_target(diff: float) -> int:
    if diff <= 0:
        diff = 1.0
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return int(max_target / diff)

def varint(n: int) -> bytes:
    if n < 0xFD:
        return struct.pack("<B", n)
    elif n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    elif n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    else:
        return b"\xff" + struct.pack("<Q", n)

class FchRPC:
    def __init__(self):
        self.url = f"http://{RPC_HOST}:{RPC_PORT}"
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(RPC_USER, RPC_PASS)
        self.session.headers.update({"Content-Type": "text/plain"})

    def call(self, method: str, params: list = None) -> Any:
        payload = {"jsonrpc": "1.0", "id": "fch-node", "method": method, "params": params or []}
        try:
            r = self.session.post(self.url, data=json.dumps(payload), timeout=RPC_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                raise RuntimeError(f"RPC error: {data['error']}")
            return data.get("result")
        except Exception as e:
            log.error(f"RPC {method} failed: {e}")
            raise

    def getblocktemplate(self) -> dict:
        return self.call("getblocktemplate", [{"rules": ["segwit"]}])

    def submitblock(self, block_hex: str) -> Any:
        return self.call("submitblock", [block_hex])

    def getblockchaininfo(self) -> dict:
        return self.call("getblockchaininfo")

rpc = FchRPC()

@dataclass
class Job:
    job_id: str
    prevhash: str
    coinb1: str
    coinb2: str
    merkle_branch: List[str]
    version: str
    nbits: str
    ntime: str
    clean_jobs: bool
    height: int
    coinbase_value: int
    network_target: int
    template: dict
    created: float = field(default_factory=time.time)

class JobManager:
    def __init__(self):
        self.current_job: Optional[Job] = None
        self.lock = asyncio.Lock()
        self.last_template_time = 0
        self.template_refresh_interval = 30

    async def refresh(self, force: bool = False) -> Optional[Job]:
        async with self.lock:
            now = time.time()
            if not force and self.current_job and (now - self.last_template_time) < self.template_refresh_interval:
                return self.current_job
            try:
                tmpl = await asyncio.get_event_loop().run_in_executor(None, rpc.getblocktemplate)
            except Exception as e:
                log.error(f"Failed to get block template: {e}")
                return self.current_job
            self.last_template_time = now
            job = self._build_job(tmpl)
            self.current_job = job
            log.info(f"New job {job.job_id} @ height {job.height} | value={job.coinbase_value/1e8:.8f} FCH")
            return job

    def _build_job(self, tmpl: dict) -> Job:
        height = tmpl["height"]
        prevhash = reverse_hex(tmpl["previousblockhash"])
        version = f"{tmpl['version']:08x}"
        nbits = tmpl["bits"]
        ntime = f"{tmpl['curtime']:08x}"
        network_target = bits_to_target(nbits)
        coinbase_value = tmpl.get("coinbasevalue", 0)

        height_script = self._encode_height(height)
        extranonce_placeholder = b"\x00" * 8
        coinbase_script = height_script + extranonce_placeholder + b"/fch-node/"

        tx_version = struct.pack("<I", 2)
        tx_in_count = varint(1)
        prevout = b"\x00" * 32 + b"\xff\xff\xff\xff"
        script_len = varint(len(coinbase_script))
        sequence = b"\xff\xff\xff\xff"

        value = struct.pack("<Q", coinbase_value)
        pk_script = b"\x76\xa9\x14" + b"\x00" * 20 + b"\x88\xac"
        pk_script_len = varint(len(pk_script))
        tx_out_count = varint(1)
        locktime = b"\x00\x00\x00\x00"

        coinbase_tx = (
            tx_version + tx_in_count + prevout + script_len + coinbase_script +
            sequence + tx_out_count + value + pk_script_len + pk_script + locktime
        )

        split_at = len(tx_version) + len(tx_in_count) + len(prevout) + 1 + len(height_script)
        coinb1 = hexlify(coinbase_tx[:split_at]).decode()
        coinb2 = hexlify(coinbase_tx[split_at + 8:]).decode()

        merkle_branch = []
        for tx in tmpl.get("transactions", [])[:12]:
            if "hash" in tx:
                merkle_branch.append(tx["hash"])

        job_id = hexlify(os.urandom(4)).decode()

        return Job(
            job_id=job_id, prevhash=prevhash, coinb1=coinb1, coinb2=coinb2,
            merkle_branch=merkle_branch, version=version, nbits=nbits, ntime=ntime,
            clean_jobs=True, height=height, coinbase_value=coinbase_value,
            network_target=network_target, template=tmpl,
        )

    @staticmethod
    def _encode_height(height: int) -> bytes:
        if height == 0:
            return b"\x00"
        h = height
        result = b""
        while h > 0:
            result += bytes([h & 0xFF])
            h >>= 8
        return bytes([len(result)]) + result

job_manager = JobManager()

@dataclass
class Worker:
    name: str
    address: str
    difficulty: float = START_DIFF
    shares: int = 0
    valid_shares: int = 0
    invalid_shares: int = 0
    last_share: float = 0.0
    hashrate: float = 0.0
    extranonce1: str = ""
    connected_at: float = field(default_factory=time.time)
    authorized: bool = False

workers: Dict[str, Worker] = {}
global_stats = {
    "start_time": time.time(),
    "total_shares": 0,
    "valid_shares": 0,
    "invalid_shares": 0,
    "blocks_found": 0,
    "last_block_time": None,
    "mode": MODE,
    "wallet": DEFAULT_WALLET,
}

def save_stats():
    stats_file = Path("logs/stats.json")
    data = {
        **global_stats,
        "hashrate_ths": sum(w.hashrate for w in workers.values()) / 1e12,
        "workers": len([w for w in workers.values() if w.authorized]),
        "uptime_seconds": int(time.time() - global_stats["start_time"]),
        "worker_details": {
            name: {
                "shares": w.shares,
                "valid": w.valid_shares,
                "hashrate_ths": round(w.hashrate / 1e12, 4),
                "difficulty": w.difficulty,
                "last_share": w.last_share,
            }
            for name, w in workers.items()
        },
    }
    try:
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save stats: {e}")

class StratumClient(asyncio.Protocol):
    def __init__(self):
        self.transport = None
        self.buffer = b""
        self.worker: Optional[Worker] = None
        self.extranonce1 = hexlify(os.urandom(4)).decode()
        self.peer = "?"

    def connection_made(self, transport):
        self.transport = transport
        self.peer = transport.get_extra_info("peername")
        log.info(f"Connection from {self.peer}")

    def connection_lost(self, exc):
        log.info(f"Disconnected: {self.peer}")
        if self.worker:
            self.worker.authorized = False

    def data_received(self, data: bytes):
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
                asyncio.create_task(self.handle(msg))
            except Exception as e:
                log.error(f"Bad message from {self.peer}: {e}")

    async def handle(self, msg: dict):
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or []

        if method == "mining.subscribe":
            await self.on_subscribe(msg_id, params)
        elif method == "mining.authorize":
            await self.on_authorize(msg_id, params)
        elif method == "mining.submit":
            await self.on_submit(msg_id, params)
        elif method == "mining.extranonce.subscribe":
            self.reply(msg_id, True)
        elif method == "mining.configure":
            self.reply(msg_id, {"version-rolling": True})
        else:
            self.error(msg_id, 20, "Unknown method")

    async def on_subscribe(self, msg_id, params):
        result = [[ ["mining.set_difficulty", "sub1"], ["mining.notify", "sub2"] ], self.extranonce1, 4]
        self.reply(msg_id, result)
        log.info(f"Subscribed {self.peer} extranonce1={self.extranonce1}")

    async def on_authorize(self, msg_id, params):
        if not params:
            self.error(msg_id, 24, "Missing worker name")
            return

        worker_name = str(params[0])
        password = str(params[1]) if len(params) > 1 else "x"

        diff = START_DIFF
        if "d=" in password:
            try:
                diff = float(password.split("d=")[1].split(",")[0])
            except Exception:
                pass

        address = worker_name.split(".")[0] if "." in worker_name else worker_name
        if not address or address.lower() in ("x", "worker"):
            address = DEFAULT_WALLET

        if worker_name not in workers:
            workers[worker_name] = Worker(name=worker_name, address=address, difficulty=diff, extranonce1=self.extranonce1)
        self.worker = workers[worker_name]
        self.worker.authorized = True
        self.worker.extranonce1 = self.extranonce1
        self.worker.difficulty = diff

        self.reply(msg_id, True)
        self.notify("mining.set_difficulty", [self.worker.difficulty])

        job = await job_manager.refresh()
        if job:
            await self.send_job(job)

        log.info(f"Authorized {worker_name} -> {address} (diff={diff})")

    async def on_submit(self, msg_id, params):
        if not self.worker or not self.worker.authorized:
            self.error(msg_id, 24, "Unauthorized")
            return

        if len(params) < 5:
            self.error(msg_id, 20, "Bad params")
            return

        worker_name, job_id, extranonce2, ntime, nonce = params[:5]
        global_stats["total_shares"] += 1
        self.worker.shares += 1
        self.worker.last_share = time.time()

        job = job_manager.current_job
        if not job or job.job_id != job_id:
            global_stats["invalid_shares"] += 1
            self.worker.invalid_shares += 1
            self.error(msg_id, 21, "Stale share")
            return

        try:
            coinbase_hex = job.coinb1 + self.worker.extranonce1 + extranonce2 + job.coinb2
            coinbase_bin = unhexlify(coinbase_hex)
            coinbase_hash = double_sha256(coinbase_bin)
        except Exception as e:
            log.warning(f"Coinbase error: {e}")
            self.error(msg_id, 20, "Bad extranonce")
            return

        merkle_root = coinbase_hash
        for branch in job.merkle_branch:
            try:
                branch_bin = unhexlify(branch)
                merkle_root = double_sha256(merkle_root + branch_bin)
            except Exception:
                pass

        try:
            version = unhexlify(job.version)
            prevhash = unhexlify(job.prevhash)
            ntime_bin = unhexlify(ntime)
            nbits = unhexlify(job.nbits)
            nonce_bin = unhexlify(nonce)

            header = version + prevhash + merkle_root + ntime_bin + nbits + nonce_bin
            header_hash = double_sha256(header)
            hash_int = int.from_bytes(header_hash, "little")
        except Exception as e:
            log.warning(f"Header error: {e}")
            self.error(msg_id, 20, "Bad header")
            return

        share_target = difficulty_to_target(self.worker.difficulty)
        if hash_int > share_target:
            global_stats["invalid_shares"] += 1
            self.worker.invalid_shares += 1
            self.error(msg_id, 23, "Low difficulty share")
            return

        global_stats["valid_shares"] += 1
        self.worker.valid_shares += 1
        self.reply(msg_id, True)
        log.info(f"Share OK from {self.worker.name} diff={self.worker.difficulty}")

        if hash_int <= job.network_target:
            log.warning("*** NETWORK DIFFICULTY MET – SUBMITTING BLOCK ***")
            await self.submit_block(header, coinbase_bin, job)

        self._update_hashrate()
        save_stats()

    async def submit_block(self, header: bytes, coinbase: bytes, job: Job):
        try:
            tx_count = varint(1 + len(job.template.get("transactions", [])))
            block = header + tx_count + coinbase
            for tx in job.template.get("transactions", []):
                if "data" in tx:
                    block += unhexlify(tx["data"])

            block_hex = hexlify(block).decode()
            result = await asyncio.get_event_loop().run_in_executor(None, rpc.submitblock, block_hex)
            if result is None or result == "":
                global_stats["blocks_found"] += 1
                global_stats["last_block_time"] = time.time()
                log.warning(f"*** BLOCK ACCEPTED BY NODE *** height~{job.height}")
                save_stats()
            else:
                log.error(f"submitblock rejected: {result}")
        except Exception as e:
            log.error(f"submitblock failed: {e}")

    async def send_job(self, job: Job):
        params = [job.job_id, job.prevhash, job.coinb1, job.coinb2, job.merkle_branch, job.version, job.nbits, job.ntime, job.clean_jobs]
        self.notify("mining.notify", params)

    def _update_hashrate(self):
        now = time.time()
        for w in workers.values():
            if w.last_share and (now - w.last_share) < 600:
                elapsed = max(now - w.connected_at, 1)
                w.hashrate = (w.valid_shares * w.difficulty * 4294967296) / elapsed

    def reply(self, msg_id, result):
        self._send({"id": msg_id, "result": result, "error": None})

    def error(self, msg_id, code, message):
        self._send({"id": msg_id, "result": None, "error": [code, message, None]})

    def notify(self, method, params):
        self._send({"id": None, "method": method, "params": params})

    def _send(self, obj: dict):
        if self.transport and not self.transport.is_closing():
            self.transport.write((json.dumps(obj) + "\n").encode("utf-8"))

async def template_refresher():
    while True:
        try:
            await job_manager.refresh(force=True)
        except Exception as e:
            log.error(f"Template refresh error: {e}")
        await asyncio.sleep(25)

async def stats_saver():
    while True:
        save_stats()
        await asyncio.sleep(10)

async def main():
    log.info("=" * 60)
    log.info("fch-node Production Solo Stratum Server")
    log.info(f"Mode          : {MODE.upper()}")
    log.info(f"Stratum       : {STRATUM_HOST}:{STRATUM_PORT}")
    log.info(f"RPC           : {RPC_HOST}:{RPC_PORT}")
    log.info(f"Default wallet: {DEFAULT_WALLET}")
    log.info(f"Start diff    : {START_DIFF}")
    log.info("=" * 60)

    try:
        info = rpc.getblockchaininfo()
        log.info(f"freecashd OK – chain={info.get('chain')} blocks={info.get('blocks')} ibd={info.get('initialblockdownload')}")
    except Exception as e:
        log.error(f"Cannot talk to freecashd: {e}")
        log.error("Start freecashd, wait until synced, set rpcuser/rpcpassword/rpcallowip!")

    await job_manager.refresh(force=True)

    loop = asyncio.get_running_loop()
    server = await loop.create_server(StratumClient, STRATUM_HOST, STRATUM_PORT)
    log.info(f"Stratum listening on {STRATUM_HOST}:{STRATUM_PORT}")

    asyncio.create_task(template_refresher())
    asyncio.create_task(stats_saver())

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutdown")
        save_stats()
