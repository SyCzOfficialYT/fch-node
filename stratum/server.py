#!/usr/bin/env python3
"""
BCH2 Solo Stratum – AxeOS / NerdQaxe++ kompatibel

WICHTIG für Accepts:
  - coinb1/coinb2 im notify == exakt Submit-Coinbase
  - merkle_branch muss zum Job passen
  - Wir minen bewusst empty blocks (nur Coinbase),
    damit Miner und Server denselben Merkle-Root haben.
"""

import socket
import threading
import json
import time
import struct
import hashlib
import logging
import binascii
import os
import yaml
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.example.yaml"

with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

RPC_HOST = cfg["rpc"]["host"]
RPC_PORT = int(cfg["rpc"]["port"])
RPC_USER = cfg["rpc"]["user"]
RPC_PASS = cfg["rpc"]["password"]
PAYOUT_ADDRESS = cfg["pool"]["payout_address"]
STRATUM_HOST = cfg["pool"].get("stratum_host", "0.0.0.0")
STRATUM_PORT = int(cfg["pool"].get("stratum_port", 3333))
START_DIFF = int(cfg["pool"].get("start_difficulty", 1000))
JOB_INTERVAL = int(cfg["pool"].get("job_interval", 20))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bch2-stratum")


def rpc(method, params=None):
    if params is None:
        params = []
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "s", "method": method, "params": params},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS),
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            log.error("RPC %s: %s", method, data["error"])
            return None
        return data.get("result")
    except Exception as e:
        log.error("RPC %s: %s", method, e)
        return None


def sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def encode_varint(n: int) -> bytes:
    if n < 0xFD:
        return struct.pack("<B", n)
    if n <= 0xFFFF:
        return struct.pack("<BH", 0xFD, n)
    if n <= 0xFFFFFFFF:
        return struct.pack("<BI", 0xFE, n)
    return struct.pack("<BQ", 0xFF, n)


def bits_to_target(nbits) -> int:
    bits = int(nbits, 16) if isinstance(nbits, str) else int(nbits)
    exp = bits >> 24
    mant = bits & 0xFFFFFF
    if exp <= 3:
        return mant >> (8 * (3 - exp))
    return mant << (8 * (exp - 3))


def difficulty_to_target(diff: float) -> int:
    return int(0x00000000FFFF0000000000000000000000000000000000000000000000000000 / max(diff, 0.0001))


def uint256_to_stratum_prevhash(h: str) -> str:
    return binascii.hexlify(binascii.unhexlify(h)[::-1]).decode()


CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _convertbits(data, frombits, tobits, pad=True):
    acc = bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for v in data:
        acc = (acc << frombits) | v
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def address_to_scriptpubkey(addr: str) -> bytes:
    info = rpc("validateaddress", [addr])
    if info and info.get("isvalid") and info.get("scriptPubKey"):
        return binascii.unhexlify(info["scriptPubKey"])
    info2 = rpc("getaddressinfo", [addr])
    if info2 and info2.get("scriptPubKey"):
        return binascii.unhexlify(info2["scriptPubKey"])
    payload = addr.lower().split(":")[-1]
    data5 = [CHARSET.index(c) for c in payload][:-8]
    decoded = bytes(_convertbits(data5, 5, 8, pad=False))
    h160 = decoded[1:21]
    return b"\x76\xa9\x14" + h160 + b"\x88\xac"


def bip34_height(height: int) -> bytes:
    if height == 0:
        return b"\x00"
    h, b = height, b""
    while h > 0:
        b += bytes([h & 0xFF])
        h >>= 8
    return bytes([len(b)]) + b


def build_coinbase_parts(height, value_sats, spk, en1: bytes, en2_size: int = 4):
    tag = b"/BCH2-Solo/"
    prefix = bip34_height(height) + en1
    suffix = tag
    script_len = len(prefix) + en2_size + len(suffix)

    p1 = b""
    p1 += struct.pack("<I", 2)
    p1 += b"\x01"
    p1 += b"\x00" * 32
    p1 += struct.pack("<I", 0xFFFFFFFF)
    p1 += encode_varint(script_len)
    p1 += prefix

    p2 = b""
    p2 += suffix
    p2 += struct.pack("<I", 0xFFFFFFFF)
    p2 += b"\x01"
    p2 += struct.pack("<Q", value_sats)
    p2 += encode_varint(len(spk)) + spk
    p2 += struct.pack("<I", 0)

    return binascii.hexlify(p1).decode(), binascii.hexlify(p2).decode()


class JobStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}
        self.current_id = None
        self.spk = None

    def ensure_spk(self):
        if self.spk is None:
            self.spk = address_to_scriptpubkey(PAYOUT_ADDRESS)
            log.info("scriptPubKey ready (%d bytes)", len(self.spk))

    def refresh(self):
        self.ensure_spk()
        tmpl = rpc("getblocktemplate", [{"rules": []}])
        if not tmpl:
            tmpl = rpc("getblocktemplate", [{"rules": ["segwit"]}])
        if not tmpl:
            log.warning("getblocktemplate failed")
            return None

        tmpl = dict(tmpl)
        tmpl["transactions"] = []

        height = tmpl["height"]
        value = tmpl["coinbasevalue"]
        nbits = tmpl["bits"]
        job_id = "%x-%x" % (height, int(time.time()) & 0xFFFFFF)

        job = {
            "id": job_id,
            "height": height,
            "value": value,
            "prevhash": tmpl["previousblockhash"],
            "version": tmpl["version"],
            "nbits": nbits if isinstance(nbits, str) else "%08x" % nbits,
            "ntime": tmpl["curtime"],
            "target": bits_to_target(nbits),
            "template": tmpl,
            "spk": self.spk,
        }
        with self.lock:
            self.jobs[job_id] = job
            while len(self.jobs) > 10:
                self.jobs.pop(next(iter(self.jobs)))
            self.current_id = job_id
        log.info("Job %s height=%s value=%.8f (empty block)", job_id, height, value / 1e8)
        return job

    def get(self, jid):
        with self.lock:
            return self.jobs.get(jid)


store = JobStore()


class Client(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.worker = "?"
        self.diff = START_DIFF
        self.en1 = os.urandom(4)
        self.en2_size = 4
        self.running = True
        self.ok = 0
        self.bad = 0

    def send(self, obj):
        try:
            self.conn.sendall((json.dumps(obj) + "\n").encode())
        except Exception:
            self.running = False

    def handle_subscribe(self, mid, params):
        en1 = binascii.hexlify(self.en1).decode()
        self.send({
            "id": mid,
            "result": [
                [["mining.notify", en1], ["mining.set_difficulty", en1]],
                en1,
                self.en2_size,
            ],
            "error": None,
        })
        log.info("subscribe %s en1=%s", self.addr, en1)

    def handle_authorize(self, mid, params):
        self.worker = params[0] if params else "?"
        self.send({"id": mid, "result": True, "error": None})
        log.info("authorize %s", self.worker)
        self.send({"id": None, "method": "mining.set_difficulty", "params": [float(self.diff)]})
        self.push_job(True)

    def handle_suggest_difficulty(self, mid, params):
        if params:
            try:
                d = float(params[0])
                if 64 <= d <= 5_000_000:
                    self.diff = int(d)
                    self.send({"id": None, "method": "mining.set_difficulty", "params": [float(self.diff)]})
                    log.info("suggest_difficulty → %s", self.diff)
            except Exception:
                pass
        self.send({"id": mid, "result": True, "error": None})

    def push_job(self, clean=True):
        job = store.refresh() if clean else None
        if job is None:
            with store.lock:
                jid = store.current_id
            job = store.get(jid) if jid else None
        if not job:
            return

        coinb1, coinb2 = build_coinbase_parts(
            job["height"], job["value"], job["spk"], self.en1, self.en2_size
        )
        prev = uint256_to_stratum_prevhash(job["prevhash"])
        ver = "%08x" % job["version"]
        bits = job["nbits"] if len(job["nbits"]) == 8 else "%08x" % int(job["nbits"], 16)
        ntime = "%08x" % job["ntime"]

        params = [job["id"], prev, coinb1, coinb2, [], ver, bits, ntime, bool(clean)]
        self.send({"id": None, "method": "mining.notify", "params": params})

    def handle_submit(self, mid, params):
        if len(params) < 5:
            self.send({"id": mid, "result": False, "error": [20, "bad params", None]})
            self.bad += 1
            return

        _, job_id, en2_hex, ntime_hex, nonce_hex = params[:5]
        job = store.get(job_id)
        if not job:
            self.send({"id": mid, "result": False, "error": [21, "stale", None]})
            self.bad += 1
            log.info("REJECT stale %s", job_id)
            return

        try:
            en2 = binascii.unhexlify(en2_hex)
            if len(en2) != self.en2_size:
                en2 = (en2 + b"\x00" * self.en2_size)[: self.en2_size]
            ntime = int(ntime_hex, 16)
            nonce = int(nonce_hex, 16)
        except Exception:
            self.send({"id": mid, "result": False, "error": [20, "bad hex", None]})
            self.bad += 1
            return

        coinb1, coinb2 = build_coinbase_parts(
            job["height"], job["value"], job["spk"], self.en1, self.en2_size
        )
        coinbase = binascii.unhexlify(coinb1) + en2 + binascii.unhexlify(coinb2)
        merkle = sha256d(coinbase)

        header = b""
        header += struct.pack("<I", job["version"])
        header += binascii.unhexlify(job["prevhash"])[::-1]
        header += merkle
        header += struct.pack("<I", ntime)
        header += struct.pack("<I", int(job["nbits"], 16))
        header += struct.pack("<I", nonce)

        h = sha256d(header)
        h_int = int.from_bytes(h[::-1], "big")
        share_target = difficulty_to_target(self.diff)

        if h_int > share_target:
            self.send({"id": mid, "result": False, "error": [23, "low difficulty", None]})
            self.bad += 1
            log.info("REJECT lowdiff worker=%s hash=%s diff_set=%s", self.worker, h[::-1].hex()[:16], self.diff)
            return

        self.send({"id": mid, "result": True, "error": None})
        self.ok += 1
        log.info("ACCEPT share #%d worker=%s hash=%s diff=%s", self.ok, self.worker, h[::-1].hex()[:16], self.diff)

        if h_int <= job["target"]:
            log.warning("*** BLOCK CANDIDATE height=%s ***", job["height"])
            block = header + encode_varint(1) + coinbase
            res = rpc("submitblock", [binascii.hexlify(block).decode()])
            if res in (None, ""):
                log.warning("*** BLOCK ACCEPTED BY NETWORK ***")
            else:
                log.error("submitblock rejected: %s", res)

    def run(self):
        buf = ""
        try:
            while self.running:
                data = self.conn.recv(8192)
                if not data:
                    break
                buf += data.decode(errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    mid = msg.get("id")
                    method = msg.get("method")
                    params = msg.get("params") or []

                    if method == "mining.subscribe":
                        self.handle_subscribe(mid, params)
                    elif method == "mining.authorize":
                        self.handle_authorize(mid, params)
                    elif method == "mining.submit":
                        self.handle_submit(mid, params)
                    elif method == "mining.extranonce.subscribe":
                        self.send({"id": mid, "result": True, "error": None})
                    elif method == "mining.suggest_difficulty":
                        self.handle_suggest_difficulty(mid, params)
                    elif method == "mining.configure":
                        self.send({"id": mid, "result": {}, "error": None})
                    else:
                        self.send({"id": mid, "result": None, "error": [20, "unknown", None]})
        except Exception as e:
            log.error("client %s: %s", self.addr, e)
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            log.info("disconnect %s ok=%d bad=%d", self.worker, self.ok, self.bad)


def job_loop():
    while True:
        try:
            store.refresh()
        except Exception as e:
            log.error("job_loop: %s", e)
        time.sleep(JOB_INTERVAL)


def main():
    log.info("=" * 50)
    log.info("BCH2 Solo Stratum (AxeOS/NerdQaxe)")
    log.info("Payout : %s", PAYOUT_ADDRESS)
    log.info("Listen : %s:%s  start_diff=%s", STRATUM_HOST, STRATUM_PORT, START_DIFF)
    log.info("=" * 50)

    store.ensure_spk()
    store.refresh()
    threading.Thread(target=job_loop, daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((STRATUM_HOST, STRATUM_PORT))
    sock.listen(16)
    log.info("waiting for miners on :%s ...", STRATUM_PORT)

    while True:
        conn, addr = sock.accept()
        log.info("connect %s", addr)
        Client(conn, addr).start()


if __name__ == "__main__":
    main()
