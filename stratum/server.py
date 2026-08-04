#!/usr/bin/env python3
"""
BCH2 Production Solo Stratum – AxeOS / NerdQaxe++ kompatibel

- coinbase = coinb1 + en1 + en2 + coinb2
- Version-Rolling: (job & ~mask) | (submitted & mask)
- prevhash notify = reverse WORD ORDER of BE (NerdQaxe does swap_endian_words)
- header validation uses LE prevhash = full byte-reverse of BE
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
from typing import List, Tuple
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
START_DIFF = int(cfg["pool"].get("start_difficulty", 256))
JOB_INTERVAL = int(cfg["pool"].get("job_interval", 25))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bch2-stratum")

STATS_PATH = Path(__file__).parent.parent / "data" / "stats.json"
STATS_PATH.parent.mkdir(parents=True, exist_ok=True)

_stats_lock = threading.Lock()
_stats = {
    "shares_ok": 0,
    "shares_bad": 0,
    "blocks_found": 0,
    "last_share_time": None,
    "last_share_diff": None,
    "last_share_hash": None,
    "best_share_diff": 0,
    "workers": {},
    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "block_rewards_total": 0.0,
}


def _save_stats():
    try:
        with _stats_lock:
            STATS_PATH.write_text(json.dumps(_stats, indent=2))
    except Exception as e:
        log.debug("stats save: %s", e)


def _record_share(ok: bool, worker: str, diff: float, hhex: str = "", block: bool = False, reward: float = 0.0):
    with _stats_lock:
        if ok:
            _stats["shares_ok"] += 1
            _stats["last_share_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _stats["last_share_diff"] = diff
            _stats["last_share_hash"] = hhex
            if diff and diff > (_stats.get("best_share_diff") or 0):
                _stats["best_share_diff"] = diff
            w = _stats["workers"].setdefault(worker, {"ok": 0, "bad": 0})
            w["ok"] += 1
        else:
            _stats["shares_bad"] += 1
            w = _stats["workers"].setdefault(worker, {"ok": 0, "bad": 0})
            w["bad"] += 1
        if block:
            _stats["blocks_found"] += 1
            _stats["block_rewards_total"] = _stats.get("block_rewards_total", 0) + reward
    _save_stats()


def rpc(method: str, params=None):
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
            log.error("RPC %s error: %s", method, data["error"])
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


def stratum_prevhash(rpc_be_hex: str) -> str:
    """Stratum prevhash for NerdQaxe/ckpool/mkpool:
    Reverse ORDER of 8x4-byte words of BE hash (not full byte-reverse).
    Firmware applies swap_endian_words → correct LE header prevhash.
    """
    h = rpc_be_hex.lower()
    if len(h) != 64:
        return binascii.hexlify(binascii.unhexlify(h)[::-1]).decode()
    return "".join(h[i : i + 8] for i in range(56, -1, -8))


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
    a = addr.lower()
    payload = a.split(":")[-1]
    data5 = [CHARSET.index(c) for c in payload if c in CHARSET][:-8]
    decoded = bytes(_convertbits(data5, 5, 8, pad=False))
    h160 = decoded[1:21]
    if len(h160) != 20:
        raise ValueError("bad hash160")
    return b"\x76\xa9\x14" + h160 + b"\x88\xac"


def bip34_height(height: int) -> bytes:
    if height == 0:
        return b"\x00"
    h, b = height, b""
    while h > 0:
        b += bytes([h & 0xFF])
        h >>= 8
    return bytes([len(b)]) + b


def build_coinbase_parts(height, value_sats, script_pubkey, en1_size=4, en2_size=4):
    tag = b"/BCH2-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = b""
    part1 += struct.pack("<I", 2)
    part1 += b"\x01"
    part1 += b"\x00" * 32
    part1 += struct.pack("<I", 0xFFFFFFFF)
    part1 += encode_varint(scriptsig_len)
    part1 += height_script
    part2 = b""
    part2 += tag
    part2 += struct.pack("<I", 0xFFFFFFFF)
    part2 += b"\x01"
    part2 += struct.pack("<Q", value_sats)
    part2 += encode_varint(len(script_pubkey)) + script_pubkey
    part2 += struct.pack("<I", 0)
    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()


def assemble_coinbase(coinb1, en1, en2, coinb2):
    return binascii.unhexlify(coinb1) + en1 + en2 + binascii.unhexlify(coinb2)


def full_merkle_root(coinbase_hash_le, other_tx_le):
    layer = [coinbase_hash_le] + other_tx_le
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [sha256d(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0]


class JobStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}
        self.current_id = None
        self.script_pubkey = None

    def ensure_spk(self):
        if self.script_pubkey is None:
            self.script_pubkey = address_to_scriptpubkey(PAYOUT_ADDRESS)
            log.info("scriptPubKey ready (%d bytes)", len(self.script_pubkey))

    def refresh(self):
        self.ensure_spk()
        tmpl = rpc("getblocktemplate", [{"rules": []}])
        if not tmpl:
            tmpl = rpc("getblocktemplate", [{"rules": ["segwit"]}])
        if not tmpl:
            log.warning("getblocktemplate failed")
            return None
        other_tx = [binascii.unhexlify(tx["txid"])[::-1] for tx in tmpl.get("transactions", [])]
        nbits = tmpl["bits"]
        job_id = f"{tmpl['height']:x}-{int(time.time()) & 0xFFFFFF:x}"
        job = {
            "id": job_id,
            "height": tmpl["height"],
            "value": tmpl["coinbasevalue"],
            "prevhash": tmpl["previousblockhash"],
            "version": tmpl["version"],
            "nbits": nbits if isinstance(nbits, str) else f"{nbits:08x}",
            "ntime": tmpl["curtime"],
            "target": bits_to_target(nbits),
            "template": tmpl,
            "spk": self.script_pubkey,
            "other_tx": other_tx,
        }
        with self.lock:
            self.jobs[job_id] = job
            if len(self.jobs) > 10:
                for k in sorted(self.jobs.keys())[:-6]:
                    self.jobs.pop(k, None)
            self.current_id = job_id
        log.info("Job %s height=%s value=%.8f txs=%d", job_id, job["height"], job["value"] / 1e8, len(other_tx))
        return job

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)


store = JobStore()


class Client(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.worker = "?"
        self.diff = START_DIFF
        self.diff_from_password = False
        self.en1 = os.urandom(4)
        self.en2_size = 4
        self.running = True
        self.shares_ok = 0
        self.shares_bad = 0

    def send(self, obj):
        try:
            self.conn.sendall((json.dumps(obj) + "\n").encode())
        except Exception:
            self.running = False

    def handle_subscribe(self, mid, params):
        en1_hex = binascii.hexlify(self.en1).decode()
        result = [[["mining.notify", en1_hex], ["mining.set_difficulty", en1_hex]], en1_hex, self.en2_size]
        self.send({"id": mid, "result": result, "error": None})
        log.info("subscribe from %s en1=%s", self.addr, en1_hex)

    def handle_authorize(self, mid, params):
        self.worker = params[0] if params else "?"
        password = params[1] if len(params) > 1 else ""
        if isinstance(password, str) and password.lower().startswith("d="):
            try:
                d = float(password[2:].strip())
                if 16 <= d <= 10_000_000:
                    self.diff = max(16, int(round(d)))
                    self.diff_from_password = True
                    log.info("password d= → difficulty %s", self.diff)
            except Exception:
                pass
        self.send({"id": mid, "result": True, "error": None})
        log.info("authorize %s  share_diff=%s", self.worker, self.diff)
        self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})
        self.push_job(clean=True)

    def handle_suggest_difficulty(self, mid, params):
        if self.diff_from_password:
            log.info("suggest_difficulty ignoriert (password d= aktiv, diff=%s)", self.diff)
            self.send({"id": mid, "result": True, "error": None})
            self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})
            return
        if params:
            try:
                d = float(params[0])
                if 16 <= d <= 10_000_000:
                    self.diff = max(16, int(round(d)))
                    log.info("suggest_difficulty → %s", self.diff)
                    self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})
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
        coinb1, coinb2 = build_coinbase_parts(job["height"], job["value"], job["spk"], len(self.en1), self.en2_size)
        branches = []
        hashes = job["other_tx"][:]
        while hashes:
            branches.append(binascii.hexlify(hashes[0][::-1]).decode())
            rest = hashes[1:]
            if not rest:
                break
            if len(rest) % 2:
                rest = rest + [rest[-1]]
            hashes = [sha256d(rest[i] + rest[i + 1]) for i in range(0, len(rest), 2)]
        params = [
            job["id"],
            stratum_prevhash(job["prevhash"]),
            coinb1,
            coinb2,
            branches,
            f"{job['version']:08x}",
            job["nbits"] if len(job["nbits"]) == 8 else f"{int(job['nbits'], 16):08x}",
            f"{job['ntime']:08x}",
            clean,
        ]
        self.send({"id": None, "method": "mining.notify", "params": params})

    def handle_submit(self, mid, params):
        if len(params) < 5:
            self.send({"id": mid, "result": False, "error": [20, "bad params", None]})
            self.shares_bad += 1
            return
        _, job_id, en2_hex, ntime_hex, nonce_hex = params[:5]
        version_hex = params[5] if len(params) >= 6 else None
        job = store.get(job_id)
        if not job:
            self.send({"id": mid, "result": False, "error": [21, "stale job", None]})
            self.shares_bad += 1
            log.info("REJECT stale job=%s", job_id)
            return
        try:
            en2 = binascii.unhexlify(en2_hex)
            if len(en2) != self.en2_size:
                en2 = (en2 + b"\x00" * self.en2_size)[: self.en2_size]
            ntime = int(ntime_hex, 16)
            nonce = int(nonce_hex, 16)
            VERSION_MASK = 0x1FFFE000
            if version_hex:
                submitted_ver = int(version_hex, 16)
                if submitted_ver >= 0x20000000:
                    version = submitted_ver
                else:
                    version = (int(job["version"]) & ~VERSION_MASK) | (submitted_ver & VERSION_MASK)
            else:
                version = int(job["version"])
        except Exception:
            self.send({"id": mid, "result": False, "error": [20, "bad hex", None]})
            self.shares_bad += 1
            return
        coinb1, coinb2 = build_coinbase_parts(job["height"], job["value"], job["spk"], len(self.en1), self.en2_size)
        coinbase_tx = assemble_coinbase(coinb1, self.en1, en2, coinb2)
        coinbase_hash = sha256d(coinbase_tx)
        merkle = full_merkle_root(coinbase_hash, job["other_tx"])
        header = b""
        header += struct.pack("<I", version)
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
            self.shares_bad += 1
            log.info("REJECT lowdiff worker=%s hash=%s diff=%s ver=%08x", self.worker, h[::-1].hex()[:16], self.diff, version)
            _record_share(False, self.worker, float(self.diff), h[::-1].hex()[:16])
            return
        self.send({"id": mid, "result": True, "error": None})
        self.shares_ok += 1
        log.info("ACCEPT share #%d worker=%s hash=%s diff=%s ver=%08x", self.shares_ok, self.worker, h[::-1].hex()[:16], self.diff, version)
        _record_share(True, self.worker, float(self.diff), h[::-1].hex()[:16])
        if h_int <= job["target"]:
            log.warning("*** BLOCK CANDIDATE *** height=%s hash=%s", job["height"], h[::-1].hex())
            tx_count = 1 + len(job["template"].get("transactions", []))
            block = header + encode_varint(tx_count) + coinbase_tx
            for tx in job["template"].get("transactions", []):
                block += binascii.unhexlify(tx["data"])
            res = rpc("submitblock", [binascii.hexlify(block).decode()])
            if res in (None, ""):
                log.warning("*** BLOCK ACCEPTED BY NETWORK ***")
                _record_share(True, self.worker, float(self.diff), h[::-1].hex()[:16], block=True, reward=job["value"] / 1e8)
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
                        self.send({"id": mid, "result": {"version-rolling": True, "version-rolling.mask": "1fffe000", "version-rolling.min-bit-count": 16}, "error": None})
                    elif mid is not None:
                        self.send({"id": mid, "result": None, "error": [20, "unknown", None]})
        except Exception as e:
            log.error("client %s: %s", self.addr, e)
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            log.info("disconnect %s ok=%d bad=%d", self.worker, self.shares_ok, self.shares_bad)


def job_loop():
    while True:
        try:
            store.refresh()
        except Exception as e:
            log.error("job_loop: %s", e)
        time.sleep(JOB_INTERVAL)


def main():
    log.info("=" * 50)
    log.info("BCH2 Solo Stratum (AxeOS/NerdQaxe compatible)")
    log.info("Payout : %s", PAYOUT_ADDRESS)
    log.info("Listen : %s:%s  start_diff=%s", STRATUM_HOST, STRATUM_PORT, START_DIFF)
    log.info("=" * 50)
    store.ensure_spk()
    store.refresh()
    _save_stats()
    threading.Thread(target=job_loop, daemon=True).start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((STRATUM_HOST, STRATUM_PORT))
    sock.listen(16)
    log.info("waiting for miners...")
    while True:
        conn, addr = sock.accept()
        log.info("connect %s", addr)
        Client(conn, addr).start()


if __name__ == "__main__":
    main()
