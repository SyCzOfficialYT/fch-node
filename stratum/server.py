#!/usr/bin/env python3
"""
BCH2 Production Solo Stratum Server
- Echte Coinbase an payout_address
- Merkle Root Berechnung
- Block Header Konstruktion
- submitblock bei gültigem Block
- RPC credentials are loaded from the BCH2 node config at request time
  so an installer/config update cannot leave a long-running Stratum process
  using stale RPC credentials.
"""

import socket
import threading
import json
import time
import struct
import hashlib
import logging
import binascii
import yaml
from pathlib import Path
from typing import Optional, List, Tuple
import requests
from requests.auth import HTTPBasicAuth

REPO_ROOT = Path(__file__).parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"
NODE_CONF_PATH = Path.home() / ".bitcoincashII" / "bitcoincashII.conf"

if not CONFIG_PATH.exists():
    CONFIG_PATH = EXAMPLE_CONFIG_PATH

with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

RPC_HOST = cfg["rpc"]["host"]
RPC_PORT = int(cfg["rpc"]["port"])
RPC_USER = cfg["rpc"]["user"]
RPC_PASS = cfg["rpc"]["password"]
PAYOUT_ADDRESS = cfg["pool"]["payout_address"]
STRATUM_HOST = cfg["pool"].get("stratum_host", "0.0.0.0")
STRATUM_PORT = int(cfg["pool"].get("stratum_port", 3333))
START_DIFF = int(cfg["pool"].get("start_difficulty", 1000))
JOB_INTERVAL = int(cfg["pool"].get("job_interval", 25))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bch2-stratum")


def _read_node_rpc_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Read the node's authoritative rpcuser/rpcpassword from bitcoincashII.conf."""
    try:
        if not NODE_CONF_PATH.is_file():
            return None, None
        user = None
        password = None
        with NODE_CONF_PATH.open(encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key == "rpcuser":
                    user = value.strip()
                elif key == "rpcpassword":
                    password = value.strip()
        return user, password
    except OSError as exc:
        log.warning("Cannot read BCH2 node config %s: %s", NODE_CONF_PATH, exc)
        return None, None


def rpc(method: str, params=None):
    if params is None:
        params = []

    node_user, node_pass = _read_node_rpc_credentials()
    rpc_user = node_user or RPC_USER
    rpc_pass = node_pass or RPC_PASS

    url = f"http://{RPC_HOST}:{RPC_PORT}"
    payload = {"jsonrpc": "1.0", "id": "stratum", "method": method, "params": params}
    try:
        r = requests.post(
            url,
            json=payload,
            auth=HTTPBasicAuth(rpc_user, rpc_pass),
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            log.error(f"RPC {method} error: {data['error']}")
            return None
        return data.get("result")
    except Exception as e:
        log.error(f"RPC {method} exception: {e}")
        return None


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def reverse_hex(h: str) -> str:
    ba = binascii.unhexlify(h)
    return binascii.hexlify(ba[::-1]).decode()


def encode_varint(n: int) -> bytes:
    if n < 0xfd:
        return struct.pack("<B", n)
    elif n <= 0xffff:
        return struct.pack("<BH", 0xfd, n)
    elif n <= 0xffffffff:
        return struct.pack("<BI", 0xfe, n)
    else:
        return struct.pack("<BQ", 0xff, n)


def bits_to_target(nbits: str) -> int:
    bits = int(nbits, 16)
    exponent = bits >> 24
    mantissa = bits & 0xffffff
    if exponent <= 3:
        target = mantissa >> (8 * (3 - exponent))
    else:
        target = mantissa << (8 * (exponent - 3))
    return target


def difficulty_to_target(diff: float) -> int:
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return int(max_target / diff)


CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
CHARSET_REV = {c: i for i, c in enumerate(CHARSET)}
CASHADDR_GENERATOR = [0x98F2BC8E61, 0x79B76D99E2, 0xF33E5FB3C4, 0xAE2EABE2A8, 0x1E4F43E470]


def _cashaddr_prefix_expand(prefix: str) -> List[int]:
    return [ord(c) & 0x1F for c in prefix] + [0]


def _cashaddr_polymod(values: List[int]) -> int:
    chk = 1
    for value in values:
        top = chk >> 35
        chk = ((chk & 0x07FFFFFFFF) << 5) ^ value
        for i, generator in enumerate(CASHADDR_GENERATOR):
            if (top >> i) & 1:
                chk ^= generator
    return chk


def _convertbits(data: List[int], frombits: int, tobits: int, pad: bool) -> List[int]:
    acc = 0
    bits = 0
    ret: List[int] = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1

    for value in data:
        if value < 0 or value >> frombits:
            raise ValueError("Invalid CashAddr data value")
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)

    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    else:
        if bits >= frombits:
            raise ValueError("Invalid CashAddr padding")
        if ((acc << (tobits - bits)) & maxv) != 0:
            raise ValueError("Non-zero CashAddr padding")

    return ret


def cashaddr_decode(addr: str) -> Tuple[int, bytes]:
    """Decode and validate a Bitcoin Cash CashAddr address.

    The previous implementation treated the 5-bit CashAddr payload as if it
    were byte-aligned. That silently produced a malformed hash160 and caused
    every normal 20-byte P2PKH address to fall through to validateaddress.
    """
    addr = addr.strip()
    if not addr:
        raise ValueError("Empty CashAddr")
    if any(c.isupper() for c in addr) and any(c.islower() for c in addr):
        raise ValueError("Mixed-case CashAddr")

    addr = addr.lower()
    if ":" not in addr:
        raise ValueError("CashAddr prefix is required")

    prefix, payload = addr.split(":", 1)
    if not prefix or not payload:
        raise ValueError("Invalid CashAddr prefix or payload")

    try:
        data = [CHARSET_REV[c] for c in payload]
    except KeyError as exc:
        raise ValueError(f"Invalid CashAddr character: {exc.args[0]}") from None

    if len(data) < 9:
        raise ValueError("CashAddr too short")

    if _cashaddr_polymod(_cashaddr_prefix_expand(prefix) + data) != 1:
        raise ValueError("Invalid CashAddr checksum")

    payload_data = data[:-8]
    decoded = bytes(_convertbits(payload_data, 5, 8, False))
    if len(decoded) < 1:
        raise ValueError("CashAddr payload is empty")

    version = decoded[0]
    hash160 = decoded[1:]

    # CashAddr version is 5 bits. BCH currently uses version 0 (P2PKH) and
    # version 1 (P2SH); reject unknown versions instead of constructing a
    # potentially incorrect coinbase output.
    if version > 31:
        raise ValueError("Invalid CashAddr version")

    return version, hash160


def address_to_scriptpubkey(addr: str) -> bytes:
    version, payload = cashaddr_decode(addr)
    if len(payload) not in (20, 24, 28, 32, 40, 48, 56, 64):
        raise ValueError(f"Invalid CashAddr payload length: {len(payload)}")

    if version == 0:
        if len(payload) != 20:
            raise ValueError("P2PKH CashAddr must contain a 20-byte hash160")
        return b"\x76\xa9\x14" + payload + b"\x88\xac"

    if version == 1:
        if len(payload) != 20:
            raise ValueError("P2SH CashAddr must contain a 20-byte hash160")
        return b"\xa9\x14" + payload + b"\x87"

    raise ValueError(f"Unsupported CashAddr version: {version}")


def serialize_coinbase_tx(height: int, value_sats: int, script_pubkey: bytes, extranonce1: bytes, extranonce2: bytes) -> bytes:
    if height < 17:
        height_script = bytes([height])
    else:
        h_bytes = b""
        h = height
        while h > 0:
            h_bytes += bytes([h & 0xff])
            h >>= 8
        height_script = bytes([len(h_bytes)]) + h_bytes
    script_sig = height_script + extranonce1 + extranonce2 + b"/BCH2-Solo/"
    tx = b""
    tx += struct.pack("<I", 2)
    tx += b"\x01"
    tx += b"\x00" * 32
    tx += struct.pack("<I", 0xffffffff)
    tx += encode_varint(len(script_sig)) + script_sig
    tx += struct.pack("<I", 0xffffffff)
    tx += b"\x01"
    tx += struct.pack("<Q", value_sats)
    tx += encode_varint(len(script_pubkey)) + script_pubkey
    tx += struct.pack("<I", 0)
    return tx


def merkle_root_from_tx_hashes(tx_hashes: List[bytes]) -> bytes:
    if not tx_hashes:
        return b"\x00" * 32
    layer = tx_hashes[:]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        next_layer = []
        for i in range(0, len(layer), 2):
            next_layer.append(sha256d(layer[i] + layer[i + 1]))
        layer = next_layer
    return layer[0]


class Job:
    def __init__(self, template: dict, script_pubkey: bytes):
        self.template = template
        self.height = template["height"]
        self.prevhash = template["previousblockhash"]
        self.nbits = template["bits"]
        self.ntime = template["curtime"]
        self.version = template["version"]
        self.coinbase_value = template["coinbasevalue"]
        self.script_pubkey = script_pubkey
        self.job_id = f"{int(time.time())}_{self.height}"
        self.target = bits_to_target(self.nbits)
        self.extranonce1 = struct.pack(">I", int(time.time()) & 0xffffffff)
        self.tx_hashes = []
        for tx in template.get("transactions", []):
            txid = binascii.unhexlify(tx["txid"])[::-1]
            self.tx_hashes.append(txid)

    def build_coinbase(self, extranonce2: bytes) -> bytes:
        return serialize_coinbase_tx(self.height, self.coinbase_value, self.script_pubkey, self.extranonce1, extranonce2)

    def build_merkle_root(self, coinbase_tx: bytes) -> bytes:
        coinbase_hash = sha256d(coinbase_tx)
        return merkle_root_from_tx_hashes([coinbase_hash] + self.tx_hashes)

    def build_header(self, merkle_root: bytes, ntime: int, nonce: int) -> bytes:
        header = b""
        header += struct.pack("<I", self.version)
        header += binascii.unhexlify(self.prevhash)[::-1]
        header += merkle_root
        header += struct.pack("<I", ntime)
        header += struct.pack("<I", int(self.nbits, 16))
        header += struct.pack("<I", nonce)
        return header

    def build_block(self, coinbase_tx: bytes, header: bytes) -> bytes:
        block = header
        tx_count = 1 + len(self.template.get("transactions", []))
        block += encode_varint(tx_count)
        block += coinbase_tx
        for tx in self.template.get("transactions", []):
            block += binascii.unhexlify(tx["data"])
        return block


current_job: Optional[Job] = None
job_lock = threading.Lock()
script_pubkey: Optional[bytes] = None
clients_lock = threading.Lock()
connected_clients = []


def init_script_pubkey():
    global script_pubkey
    try:
        script_pubkey = address_to_scriptpubkey(PAYOUT_ADDRESS)
        log.info(f"Payout scriptPubKey ready for {PAYOUT_ADDRESS}")
    except Exception as e:
        log.error(f"Cannot decode payout address: {e}")
        info = rpc("validateaddress", [PAYOUT_ADDRESS])
        if info and info.get("isvalid") and info.get("scriptPubKey"):
            script_pubkey = binascii.unhexlify(info["scriptPubKey"])
            log.info("Got scriptPubKey via RPC validateaddress")
        else:
            raise RuntimeError("Cannot create scriptPubKey for payout address")


def create_job() -> Optional[Job]:
    global current_job
    tmpl = rpc("getblocktemplate", [{"rules": ["segwit"]}])
    if not tmpl:
        log.warning("getblocktemplate failed")
        return None
    if script_pubkey is None:
        init_script_pubkey()
    job = Job(tmpl, script_pubkey)
    with job_lock:
        current_job = job
    log.info(f"New job height={job.height} value={job.coinbase_value/1e8:.8f} BCH2")
    return job


def job_updater():
    while True:
        create_job()
        with clients_lock:
            for c in connected_clients:
                try:
                    c.send_job()
                except Exception:
                    pass
        time.sleep(JOB_INTERVAL)


class StratumClient(threading.Thread):
    def __init__(self, conn: socket.socket, addr):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.worker = "unknown"
        self.difficulty = START_DIFF
        self.running = True
        self.extranonce1 = None
        self.shares = 0
        self.blocks_found = 0

    def send(self, obj: dict):
        try:
            self.conn.sendall((json.dumps(obj) + "\n").encode())
        except Exception:
            self.running = False

    def handle_subscribe(self, msg_id):
        self.extranonce1 = struct.pack(">I", int(time.time() * 1000) & 0xffffffff)
        en1_hex = binascii.hexlify(self.extranonce1).decode()
        result = [[["mining.notify", "bch2solo"], ["mining.set_difficulty", "bch2solo"]], en1_hex, 4]
        self.send({"id": msg_id, "result": result, "error": None})

    def handle_authorize(self, msg_id, params):
        self.worker = params[0] if params else "unknown"
        log.info(f"Authorized {self.worker} from {self.addr}")
        self.send({"id": msg_id, "result": True, "error": None})
        self.send({"id": None, "method": "mining.set_difficulty", "params": [self.difficulty]})
        self.send_job()

    def send_job(self):
        with job_lock:
            job = current_job
        if not job:
            return
        prevhash_swab = reverse_hex(job.prevhash)
        version_hex = f"{job.version:08x}"
        nbits_hex = job.nbits if len(job.nbits) == 8 else f"{int(job.nbits, 16):08x}"
        ntime_hex = f"{job.ntime:08x}"
        coinb1 = "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff"
        coinb2 = "ffffffff01" + "00" * 8 + "00000000"
        params = [job.job_id, prevhash_swab, coinb1, coinb2, [], version_hex, nbits_hex, ntime_hex, True]
        self.send({"id": None, "method": "mining.notify", "params": params})

    def handle_submit(self, msg_id, params):
        if len(params) < 5:
            self.send({"id": msg_id, "result": False, "error": [20, "Invalid params", None]})
            return
        worker, job_id, en2_hex, ntime_hex, nonce_hex = params[:5]
        self.shares += 1
        with job_lock:
            job = current_job
        if not job or job.job_id != job_id:
            self.send({"id": msg_id, "result": False, "error": [21, "Stale job", None]})
            return
        try:
            extranonce2 = binascii.unhexlify(en2_hex)
            ntime = int(ntime_hex, 16)
            nonce = int(nonce_hex, 16)
        except Exception:
            self.send({"id": msg_id, "result": False, "error": [20, "Bad hex", None]})
            return
        try:
            coinbase_tx = job.build_coinbase(extranonce2)
            merkle = job.build_merkle_root(coinbase_tx)
            header = job.build_header(merkle, ntime, nonce)
            header_hash = sha256d(header)
            hash_int = int.from_bytes(header_hash[::-1], "big")
        except Exception as e:
            log.error(f"Build error: {e}")
            self.send({"id": msg_id, "result": False, "error": [20, "Build failed", None]})
            return
        share_target = difficulty_to_target(self.difficulty)
        network_target = job.target
        if hash_int > share_target:
            self.send({"id": msg_id, "result": False, "error": [23, "Low difficulty", None]})
            return
        self.send({"id": msg_id, "result": True, "error": None})
        if hash_int <= network_target:
            block = job.build_block(coinbase_tx, header)
            block_hex = binascii.hexlify(block).decode()
            result = rpc("submitblock", [block_hex])
            if result is None:
                log.info(f"BLOCK FOUND by {self.worker} at height {job.height}")
                self.blocks_found += 1
            else:
                log.warning(f"submitblock result: {result}")

    def run(self):
        with clients_lock:
            connected_clients.append(self)
        try:
            while self.running:
                data = self.conn.recv(4096)
                if not data:
                    break
                for line in data.decode(errors="ignore").splitlines():
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                        method = msg.get("method")
                        msg_id = msg.get("id")
                        params = msg.get("params", [])
                        if method == "mining.subscribe":
                            self.handle_subscribe(msg_id)
                        elif method == "mining.authorize":
                            self.handle_authorize(msg_id, params)
                        elif method == "mining.submit":
                            self.handle_submit(msg_id, params)
                        else:
                            self.send({"id": msg_id, "result": None, "error": [20, "Method not supported", None]})
                    except json.JSONDecodeError:
                        self.send({"id": None, "result": None, "error": [20, "Invalid JSON", None]})
        except Exception as e:
            log.debug(f"Client {self.addr} disconnected: {e}")
        finally:
            with clients_lock:
                if self in connected_clients:
                    connected_clients.remove(self)
            try:
                self.conn.close()
            except Exception:
                pass


def start_stratum():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((STRATUM_HOST, STRATUM_PORT))
    server.listen(8)
    log.info("=" * 60)
    log.info("BCH2 Production Solo Stratum")
    log.info(f"Payout : {PAYOUT_ADDRESS}")
    log.info(f"Listen : {STRATUM_HOST}:{STRATUM_PORT}")
    log.info("=" * 60)
    init_script_pubkey()
    threading.Thread(target=job_updater, daemon=True).start()
    log.info("Stratum ready – waiting for NerdQaxe++")
    while True:
        conn, addr = server.accept()
        log.info(f"Miner connected from {addr}")
        StratumClient(conn, addr).start()


if __name__ == "__main__":
    start_stratum()
