"""ESP-Miner/NerdQaxe++ compatible Stratum share validation.

ESP-Miner's BM job path applies an additional 32-bit-word endian transform to
Stratum's previous-block hash before the ASIC hashes the header.  The pool
must reproduce that exact byte layout when validating a nonce returned by the
NerdQaxe++; the canonical Bitcoin block header remains separate for
submitblock.
"""

from __future__ import annotations

import binascii
import hashlib
import struct
from typing import Optional


def _reverse_endianness_per_word(data: bytes) -> bytes:
    if len(data) % 4:
        raise ValueError("32-bit word transform requires a multiple of 4 bytes")
    return b"".join(data[i : i + 4][::-1] for i in range(0, len(data), 4))


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def build_asic_header(job, merkle_root: bytes, ntime: int, nonce: int, version: int) -> bytes:
    """Build the byte layout used by ESP-Miner's test_nonce_value().

    ESP-Miner receives the normal Stratum prevhash, performs
    reverse_endianness_per_word() and then reverses the 32-bit word order when
    constructing its BM job. test_nonce_value() reverses the word order again,
    leaving the per-word endian transform of the Stratum prevhash.
    """
    stratum_prevhash = binascii.unhexlify(job.prevhash)[::-1]
    asic_prevhash = _reverse_endianness_per_word(stratum_prevhash)
    return (
        struct.pack("<I", version & 0xFFFFFFFF)
        + asic_prevhash
        + merkle_root
        + struct.pack("<I", ntime & 0xFFFFFFFF)
        + struct.pack("<I", int(job.nbits, 16) & 0xFFFFFFFF)
        + struct.pack("<I", nonce & 0xFFFFFFFF)
    )


def hash_int(header: bytes) -> int:
    return int.from_bytes(sha256d(header)[::-1], "big")


def target_to_difficulty(target: int) -> float:
    if target <= 0:
        return float("inf")
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return max_target / target


def patch(server_module) -> None:
    """Patch StratumClient.handle_submit with ESP-Miner-compatible validation."""
    original = server_module.StratumClient.handle_submit

    if getattr(original, "_asic_compat", False):
        return

    def handle_submit(self, msg_id, params):
        if len(params) < 5:
            self.send({"id": msg_id, "result": False, "error": [20, "Invalid params", None]})
            return

        worker, job_id, en2_hex, ntime_hex, nonce_hex = params[:5]
        version_bits_hex: Optional[str] = params[5] if len(params) >= 6 else None

        with server_module.job_lock:
            job = server_module.current_job
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
            server_module.log.warning("Invalid share submission from %s: %s", self.worker, exc)
            self.send({"id": msg_id, "result": False, "error": [20, str(exc), None]})
            return

        try:
            coinbase_tx = job.build_coinbase(self.extranonce1, extranonce2)
            merkle = job.build_merkle_root(coinbase_tx)
            canonical_header = job.build_header(merkle, ntime, nonce, submitted_version)
            canonical_hash = server_module.sha256d(canonical_header)
            canonical_int = int.from_bytes(canonical_hash[::-1], "big")

            asic_header = build_asic_header(job, merkle, ntime, nonce, submitted_version)
            asic_hash = sha256d(asic_header)
            asic_int = int.from_bytes(asic_hash[::-1], "big")
        except Exception as exc:
            server_module.log.error("Build error: %s", exc)
            self.send({"id": msg_id, "result": False, "error": [20, "Build failed", None]})
            return

        share_target = server_module.difficulty_to_target(self.difficulty)
        network_target = job.target
        canonical_diff = target_to_difficulty(canonical_int)
        asic_diff = target_to_difficulty(asic_int)

        if asic_int <= share_target:
            accepted_hash = asic_int
            accepted_diff = asic_diff
            accepted_header = asic_header
            validation_mode = "esp-miner"
        elif canonical_int <= share_target:
            accepted_hash = canonical_int
            accepted_diff = canonical_diff
            accepted_header = canonical_header
            validation_mode = "canonical"
        else:
            server_module.log.warning(
                "Share rejected: job=%s worker=%s nonce=%08x ntime=%08x "
                "version_bits=%s version=%08x canonical_diff=%.8f "
                "asic_diff=%.2f required=%s canonical_hash=%064x asic_hash=%064x "
                "merkle=%s nbits=%s",
                job.job_id,
                self.worker,
                nonce,
                ntime,
                version_bits_hex or "none",
                submitted_version,
                canonical_diff,
                asic_diff,
                self.difficulty,
                canonical_int,
                asic_int,
                merkle.hex(),
                job.nbits,
            )
            self.send({"id": msg_id, "result": False, "error": [23, "Low difficulty", None]})
            return

        self.shares += 1
        self.send({"id": msg_id, "result": True, "error": None})
        server_module.log.info(
            "Accepted share: job=%s worker=%s nonce=%08x ntime=%08x "
            "version_bits=%s version=%08x diff=%.2f/%s mode=%s "
            "canonical_diff=%.8f asic_diff=%.2f",
            job.job_id,
            self.worker,
            nonce,
            ntime,
            version_bits_hex or "none",
            submitted_version,
            accepted_diff,
            self.difficulty,
            validation_mode,
            canonical_diff,
            asic_diff,
        )

        # A network-valid canonical header can be submitted directly.  If the
        # ESP-Miner-compatible representation reaches network difficulty first,
        # try the corresponding header as well; only a successful RPC result is
        # counted as a found block.
        if canonical_int <= network_target:
            block = job.build_block(coinbase_tx, canonical_header)
            result = server_module.rpc("submitblock", [binascii.hexlify(block).decode()])
            if result is None:
                self.blocks_found += 1
                server_module.log.info("BLOCK FOUND: height=%s hash=%064x", job.height, canonical_int)
            else:
                server_module.log.error("submitblock rejected: %s", result)
        elif asic_int <= network_target:
            block = job.build_block(coinbase_tx, accepted_header)
            result = server_module.rpc("submitblock", [binascii.hexlify(block).decode()])
            if result is None:
                self.blocks_found += 1
                server_module.log.info("BLOCK FOUND: height=%s hash=%064x mode=esp-miner", job.height, asic_int)
            else:
                server_module.log.error("submitblock rejected for esp-miner header: %s", result)

    handle_submit._asic_compat = True
    server_module.StratumClient.handle_submit = handle_submit
