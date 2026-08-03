#!/usr/bin/env python3
"""BCH2 production solo Stratum server."""

import binascii
import hashlib
import json
import logging
import socket
import struct
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests
import yaml
from requests.auth import HTTPBasicAuth

REPO_ROOT = Path(__file__).parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.yaml"
NODE_CONF_PATH = Path.home() / ".bitcoincashII" / "bitcoincashII.conf"
if not CONFIG_PATH.exists():
    CONFIG_PATH = EXAMPLE_CONFIG_PATH

with CONFIG_PATH.open(encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

RPC_HOST = cfg["rpc"]["host"]
RPC_PORT = int(cfg["rpc"]["port"])
RPC_USER = cfg["rpc"]["user"]
RPC_PASS = cfg["rpc"]["password"]
PAYOUT_ADDRESS = cfg["pool"]["payout_address"]
STRATUM_HOST = cfg["pool"].get("stratum_host", "0.0.0.0")
STRATUM_PORT = int(cfg["pool"].get("stratum_port", 3333))
START_DIFF = float(cfg["pool"].get("start_difficulty", 1000))
JOB_INTERVAL = int(cfg["pool"].get("job_interval", 30))
# BIP310/BIP320 standard version-rolling mask.  NerdQaxe++ uses this
# extension and sends the rolled bits as the sixth mining.submit parameter.
VERSION_ROLLING_MASK = 0x1FFFE000

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bch2-stratum")


def _read_node_rpc_credentials() -> Tuple[Optional[str], Optional[str]]:
    try:
        if not NODE_CONF_PATH.is_file():
            return None, None
        user = password = None
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
        response = requests.post(
            url,
            json=payload,
            auth=HTTPBasicAuth(rpc_user, rpc_pass),
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            log.error("RPC %s error: %s", method, data["error"])
            return None
        return data.get("result")
    except Exception as exc:
        log.error("RPC %s exception: %s", method, exc)
        return None


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def reverse_hex(value: str) -> str:
    return binascii.hexlify(binascii.unhexlify(value)[::-1]).decode()


def encode_varint(n: int) -> bytes:
    if n < 0xFD:
        return struct.pack("<B", n)
    if n <= 0xFFFF:
        return struct.pack("<BH", 0xFD, n)
    if n <= 0xFFFFFFFF:
        return struct.pack("<BI", 0xFE, n)
    return struct.pack("<BQ", 0xFF, n)


def bits_to_target(nbits: str) -> int:
    compact = int(nbits, 16)
    exponent = compact >> 24
    mantissa = compact & 0xFFFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def difficulty_to_target(diff: float) -> int:
    # Stratum SHA-256 difficulty-1 target, as used by standard SHA-256 ASICs.
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return int(max_target / diff)


def target_to_difficulty(target: int) -> float:
    if target <= 0:
        return float("inf")
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return max_target / target


CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
CHARSET_REV = {c: i for i, c in enumerate(CHARSET)}
CASHADDR_GENERATOR = [
    0x98F2BC8E61,
    0x79B76D99E2,
    0xF33E5FB3C4,
    0xAE2EABE2A8,
    0x1E4F43E470,
]


def _cashaddr_prefix_expand(prefix: str) -> List[int]:
    return [ord(c) & 0x1F for c in prefix] + [0]


def _cashaddr_polymod(values: List[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 35
        checksum = ((checksum & 0x07FFFFFFFF) << 5) ^ value
        for i, generator in enumerate(CASHADDR_GENERATOR):
            if (top >> i) & 1:
                checksum ^= generator
    return checksum


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
    decoded = bytes(_convertbits(data[:-8], 5, 8, False))
    if not decoded:
        raise ValueError("CashAddr payload is empty")
    version = decoded[0]
    payload_bytes = decoded[1:]
    if version > 31:
        raise ValueError("Invalid CashAddr version")
    return version, payload_bytes


def address_to_scriptpubkey(addr: str) -> bytes:
    version, payload = cashaddr_decode(addr)
    if version == 0:
        if len(payload) != 20:
            raise ValueError("P2PKH CashAddr must contain a 20-byte hash160")
        return b"\x76\xa9\x14" + payload + b"\x88\xac"
    if version == 1:
        if len(payload) != 20:
            raise ValueError("P2SH CashAddr must contain a 20-byte hash160")
        return b"\xa9\x14" + payload + b"\x87"
    raise ValueError(f"Unsupported CashAddr version: {version}")


def serialize_coinbase_tx(
    height: int,
    value_sats: int,
    script_pubkey: bytes,
    extranonce1: bytes,
    extranonce2: bytes,
) -> bytes:
    h_bytes = b""
    h = height
    while h > 0:
        h_bytes += bytes([h & 0xFF])
        h >>= 8
    height_script = bytes([len(h_bytes)]) + h_bytes
    script_sig = height_script + extranonce1 + extranonce2 + b"/BCH2-Solo/"
    if not 2 <= len(script_sig) <= 100:
        raise ValueError(f"Coinbase scriptSig length {len(script_sig)} outside 2..100")
    tx = struct.pack("<I", 2)
    tx += b"\x01" + b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
    tx += encode_varint(len(script_sig)) + script_sig + struct.pack("<I", 0xFFFFFFFF)
    tx += b"\x01" + struct.pack("<Q", value_sats)
    tx += encode_varint(len(script_pubkey)) + script_pubkey + struct.pack("<I", 0)
    return tx


def merkle_root_from_tx_hashes(tx_hashes: List[bytes]) -> bytes:
    if not tx_hashes:
        return b"\x00" * 32
    layer = tx_hashes[:]
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [sha256d(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0]


def merkle_branches_for_coinbase(tx_hashes: List[bytes]) -> List[bytes]:
    layer = [b"\x00" * 32] + tx_hashes
    branches: List[bytes] = []
    index = 0
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        branches.append(layer[index ^ 1])
        layer = [sha256d(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
        index //= 2
    return branches


class Job:
    def __init__(self, template: dict, script_pubkey: bytes):
        self.template = template
        self.height = template["height"]
        self.prevhash = template["previousblockhash"]
        self.nbits = template["bits"]
        self.ntime = template["curtime"]
        self.version = int(template["version"]) & 0xFFFFFFFF
        self.coinbase_value = template["coinbasevalue"]
        self.script_pubkey = script_pubkey
        self.job_id = f"{int(time.time())}_{self.height}"
        self.target = bits_to_target(self.nbits)
        self.tx_hashes = [binascii.unhexlify(tx["txid"])[::-1] for tx in template.get("transactions", [])]

    def build_coinbase(self, extranonce1: bytes, extranonce2: bytes) -> bytes:
        return serialize_coinbase_tx(
            self.height,
            self.coinbase_value,
            self.script_pubkey,
            extranonce1,
            extranonce2,
        )

    def coinbase_parts(self, extranonce1: bytes) -> Tuple[bytes, bytes]:
        h = self.height
        h_bytes = b""
        while h > 0:
            h_bytes += bytes([h & 0xFF])
            h >>= 8
        height_script = bytes([len(h_bytes)]) + h_bytes
        script_sig = height_script + extranonce1 + (b"\x00" * 4) + b"/BCH2-Solo/"
        if not 2 <= len(script_sig) <= 100:
            raise ValueError(f"Coinbase scriptSig length {len(script_sig)} outside 2..100")
        prefix = struct.pack("<I", 2)
        prefix += b"\x01" + b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
        prefix += encode_varint(len(script_sig)) + height_script + extranonce1
        suffix = b"\x00" * 4 + b"/BCH2-Solo/" + struct.pack("<I", 0xFFFFFFFF)
        suffix += b"\x01" + struct.pack("<Q", self.coinbase_value)
        suffix += encode_varint(len(self.script_pubkey)) + self.script_pubkey + struct.pack("<I", 0)
        return prefix, suffix

    def build_merkle_root(self, coinbase_tx: bytes) -> bytes:
        return merkle_root_from_tx_hashes([sha256d(coinbase_tx)] + self.tx_hashes)

    def build_header(
        self,
        merkle_root: bytes,
        ntime: int,
        nonce: int,
        version: Optional[int] = None,
    ) -> bytes:
        header_version = self.version if version is None else version
        return (
            struct.pack("<I", header_version & 0xFFFFFFFF)
            + binascii.unhexlify(self.prevhash)[::-1]
            + merkle_root
            + struct.pack("<I", ntime & 0xFFFFFFFF)
            + struct.pack("<I", int(self.nbits, 16) & 0xFFFFFFFF)
            + struct.pack("<I", nonce & 0xFFFFFFFF)
        )

    def build_block(self, coinbase_tx: bytes, header: bytes) -> bytes:
        block = header
        block += encode_varint(1 + len(self.template.get("transactions", [])))
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
        log.info("Payout scriptPubKey ready for %s", PAYOUT_ADDRESS)
    except Exception as exc:
        log.warning("Local CashAddr decode failed: %s; asking node", exc)
        info = rpc("validateaddress", [PAYOUT_ADDRESS])
        if info and info.get("isvalid") and info.get("scriptPubKey"):
            script_pubkey = binascii.unhexlify(info["scriptPubKey"])
            log.info("Got scriptPubKey via RPC validateaddress")
        else:
            raise RuntimeError("Cannot create scriptPubKey for payout address")


def create_job() -> Optional[Job]:
    global current_job
    # BCH2 disables SegWit post-fork; request the generic template without
    # advertising a SegWit rule that this chain does not use.
    tmpl = rpc("getblocktemplate", [{"rules": []}])
    if not tmpl:
        log.warning("getblocktemplate failed")
        return None
    if script_pubkey is None:
        init_script_pubkey()
    job = Job(tmpl, script_pubkey)
    with job_lock:
        current_job = job
    log.info(
        "New job height=%s txs=%s value=%.8f BCH2 bits=%s version=%08x",
        job.height,
        len(job.tx_hashes),
        job.coinbase_value / 1e8,
        job.nbits,
        job.version,
    )
    return job


def job_updater():
    while True:
        create_job()
        with clients_lock:
            for client in list(connected_clients):
                try:
                    client.send_job()
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
        self.extranonce1: Optional[bytes] = None
        self.shares = 0
        self.blocks_found = 0
        self.version_rolling_enabled = False
        self.version_mask = VERSION_ROLLING_MASK

    def send(self, obj: dict):
        try:
            self.conn.sendall((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        except OSError:
            self.running = False

    def handle_configure(self, msg_id, params):
        extensions = params[0] if params and isinstance(params[0], list) else []
        extension_params = params[1] if len(params) > 1 and isinstance(params[1], dict) else {}
        requested_mask = extension_params.get("version-rolling.mask", "ffffffff")
        try:
            miner_mask = int(str(requested_mask), 16) & 0xFFFFFFFF
        except (TypeError, ValueError):
            miner_mask = 0
        negotiated = VERSION_ROLLING_MASK & miner_mask
        self.version_mask = negotiated
        self.version_rolling_enabled = "version-rolling" in extensions and negotiated != 0
        result = {}
        if "version-rolling" in extensions:
            result["version-rolling"] = self.version_rolling_enabled
            result["version-rolling.mask"] = f"{self.version_mask:08x}"
        self.send({"id": msg_id, "result": result, "error": None})
        if self.version_rolling_enabled:
            self.send({"id": None, "method": "mining.set_version_mask", "params": [f"{self.version_mask:08x}"]})
        log.info(
            "Version rolling %s for %s mask=%08x miner_mask=%08x",
            "enabled" if self.version_rolling_enabled else "disabled",
            self.addr,
            self.version_mask,
            miner_mask,
        )

    def handle_set_version_mask(self, msg_id, params):
        if not params:
            self.send({"id": msg_id, "result": False, "error": [20, "Missing version mask", None]})
            return
        try:
            requested = int(str(params[0]), 16) & 0xFFFFFFFF
        except (TypeError, ValueError):
            self.send({"id": msg_id, "result": False, "error": [20, "Invalid version mask", None]})
            return
        self.version_mask &= requested
        self.version_rolling_enabled = self.version_mask != 0
        self.send({"id": msg_id, "result": True, "error": None})

    def handle_subscribe(self, msg_id):
        self.extranonce1 = struct.pack(">I", int(time.time() * 1000) & 0xFFFFFFFF)
        en1_hex = binascii.hexlify(self.extranonce1).decode()
        self.send({
            "id": msg_id,
            "result": [
                [["mining.notify", "bch2solo"], ["mining.set_difficulty", "bch2solo"]],
                en1_hex,
                4,
            ],
            "error": None,
        })

    def handle_authorize(self, msg_id, params):
        self.worker = params[0] if params else "unknown"
        log.info("Authorized %s from %s", self.worker, self.addr)
        self.send({"id": msg_id, "result": True, "error": None})
        self.send({"id": None, "method": "mining.set_difficulty", "params": [self.difficulty]})
        self.send_job()

    def send_job(self):
        with job_lock:
            job = current_job
        if not job or self.extranonce1 is None:
            return
        params = [
            job.job_id,
            reverse_hex(job.prevhash),
            binascii.hexlify(job.coinbase_parts(self.extranonce1)[0]).decode(),
            binascii.hexlify(job.coinbase_parts(self.extranonce1)[1]).decode(),
            [binascii.hexlify(branch).decode() for branch in merkle_branches_for_coinbase(job.tx_hashes)],
            f"{job.version:08x}",
            job.nbits if len(job.nbits) == 8 else f"{int(job.nbits, 16):08x}",
            f"{job.ntime:08x}",
            True,
        ]
        self.send({"id": None, "method": "mining.notify", "params": params})

    def _effective_version(self, job: Job, version_bits: Optional[int]) -> int:
        if version_bits is None:
            return job.version
        if not self.version_rolling_enabled:
            # Some NerdQaxe/ESP-Miner versions can send the version bits even
            # when mining.configure was omitted. Treat the field as BIP310
            # version bits only when it fits the standard rolling mask.
            if version_bits & ~VERSION_ROLLING_MASK:
                raise ValueError("Version rolling is not enabled")
            mask = VERSION_ROLLING_MASK
        else:
            mask = self.version_mask
        if version_bits & ~mask:
            raise ValueError("Version bits outside negotiated mask")
        return ((job.version & ~mask) | (version_bits & mask)) & 0xFFFFFFFF

    def handle_submit(self, msg_id, params):
        if len(params) < 5:
            self.send({"id": msg_id, "result": False, "error": [20, "Invalid params", None]})
            return
        worker, job_id, en2_hex, ntime_hex, nonce_hex = params[:5]
        version_bits_hex = params[5] if len(params) >= 6 else None
        with job_lock:
            job = current_job
        if not job or job.job_id != job_id:
            self.send({"id": msg_id, "result": False, "error": [21, "Stale job", None]})
            return
        try:
            extranonce2 = binascii.unhexlify(en2_hex)
            if len(extranonce2) != 4:
                raise ValueError("extranonce2 must be 4 bytes")
            ntime = int(ntime_hex, 16)
            nonce = int(nonce_hex, 16)
            version_bits = int(version_bits_hex, 16) if version_bits_hex is not None else None
            if version_bits is not None and version_bits > 0xFFFFFFFF:
                raise ValueError("version bits out of range")
            submitted_version = self._effective_version(job, version_bits)
        except ValueError as exc:
            log.warning("Invalid share submission from %s: %s", self.worker, exc)
            self.send({"id": msg_id, "result": False, "error": [20, str(exc), None]})
            return
        try:
            coinbase_tx = job.build_coinbase(self.extranonce1, extranonce2)
            merkle = job.build_merkle_root(coinbase_tx)
            header = job.build_header(merkle, ntime, nonce, submitted_version)
            header_hash = sha256d(header)
            hash_int = int.from_bytes(header_hash[::-1], "big")
        except Exception as exc:
            log.error("Build error: %s", exc)
            self.send({"id": msg_id, "result": False, "error": [20, "Build failed", None]})
            return

        share_target = difficulty_to_target(self.difficulty)
        network_target = job.target
        actual_diff = target_to_difficulty(hash_int)
        if hash_int > share_target:
            log.warning(
                "Share rejected: job=%s worker=%s nonce=%08x ntime=%08x "
                "version_bits=%s version=%08x diff=%.2f required=%s "
                "hash=%064x merkle=%s nbits=%s",
                job.job_id,
                self.worker,
                nonce,
                ntime,
                version_bits_hex or "none",
                submitted_version,
                actual_diff,
                self.difficulty,
                hash_int,
                merkle.hex(),
                job.nbits,
            )
            self.send({"id": msg_id, "result": False, "error": [23, "Low difficulty", None]})
            return

        self.shares += 1
        self.send({"id": msg_id, "result": True, "error": None})
        log.info(
            "Accepted share: job=%s worker=%s nonce=%08x ntime=%08x "
            "version_bits=%s version=%08x diff=%.2f/%s",
            job.job_id,
            self.worker,
            nonce,
            ntime,
            version_bits_hex or "none",
            submitted_version,
            actual_diff,
            self.difficulty,
        )

        if hash_int <= network_target:
            block = job.build_block(coinbase_tx, header)
            result = rpc("submitblock", [binascii.hexlify(block).decode()])
            if result is None:
                self.blocks_found += 1
                log.info("BLOCK FOUND: height=%s hash=%064x", job.height, hash_int)
            else:
                log.error("submitblock rejected: %s", result)

    def run(self):
        with clients_lock:
            connected_clients.append(self)
        log.info("Miner connected from %s", self.addr)
        buffer = b""
        try:
            while self.running:
                data = self.conn.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line.decode())
                        method = msg.get("method")
                        msg_id = msg.get("id")
                        params = msg.get("params", [])
                        if method == "mining.configure":
                            self.handle_configure(msg_id, params)
                        elif method == "mining.set_version_mask":
                            self.handle_set_version_mask(msg_id, params)
                        elif method == "mining.subscribe":
                            self.handle_subscribe(msg_id)
                        elif method == "mining.authorize":
                            self.handle_authorize(msg_id, params)
                        elif method == "mining.submit":
                            self.handle_submit(msg_id, params)
                        else:
                            self.send({"id": msg_id, "result": None, "error": [20, "Method not supported", None]})
                    except Exception as exc:
                        log.error("Stratum message error: %s", exc)
        finally:
            self.running = False
            with clients_lock:
                if self in connected_clients:
                    connected_clients.remove(self)
            try:
                self.conn.close()
            except OSError:
                pass
            log.info("Miner disconnected from %s", self.addr)


def main():
    init_script_pubkey()
    create_job()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((STRATUM_HOST, STRATUM_PORT))
    server.listen(16)
    threading.Thread(target=job_updater, daemon=True).start()

    log.info("=" * 60)
    log.info("BCH2 Production Solo Stratum")
    log.info("Payout : %s", PAYOUT_ADDRESS)
    log.info("Listen : %s:%s", STRATUM_HOST, STRATUM_PORT)
    log.info("Version rolling mask: %08x", VERSION_ROLLING_MASK)
    log.info("=" * 60)
    log.info("Stratum ready – waiting for NerdQaxe++")

    try:
        while True:
            conn, addr = server.accept()
            StratumClient(conn, addr).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    main()
