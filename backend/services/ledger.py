"""Tamper-evident append-only event ledger using SHA-256 chaining and HMAC-SHA256."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from backend.models.schemas import LedgerEntry, LedgerVerifyResponse, utc_now_iso

GENESIS_PREV_HASH = "0" * 64


def canonical_json(data: dict[str, Any]) -> str:
    """Deterministic JSON serialization for cryptographic hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_entry_hash(prev_hash: str, canonical_event_json: str) -> str:
    """Compute sha256(prev_hash + canonical_json(event))."""
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("utf-8"))
    digest.update(canonical_event_json.encode("utf-8"))
    return digest.hexdigest()


def compute_hmac_signature(secret: str, entry_hash: str, seq: int, run_id: str) -> str:
    """Compute HMAC-SHA256 over (seq, run_id, entry_hash) using the server secret."""
    msg = f"{seq}:{run_id}:{entry_hash}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def build_ledger_entry(
    *,
    seq: int,
    run_id: str,
    node: str,
    event_type: str,
    payload: dict[str, Any],
    prev_hash: str,
    secret: str,
    created_at: str | None = None,
) -> LedgerEntry:
    """Create a cryptographically chained and HMAC-signed ledger entry."""
    timestamp = created_at or utc_now_iso()
    envelope = {
        "created_at": timestamp,
        "event_type": event_type,
        "node": node,
        "payload": payload,
        "run_id": run_id,
        "seq": seq,
    }
    payload_str = canonical_json(envelope)
    entry_hash = compute_entry_hash(prev_hash, payload_str)
    signature = compute_hmac_signature(secret, entry_hash, seq, run_id)
    return LedgerEntry(
        seq=seq,
        run_id=run_id,
        event_type=event_type,
        node=node,
        payload_json=payload_str,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        hmac_signature=signature,
        created_at=timestamp,
    )


def verify_ledger_chain(
    run_id: str,
    entries: list[LedgerEntry],
    secret: str,
) -> LedgerVerifyResponse:
    """Recompute the SHA-256 chain and HMAC-SHA256 signatures and report the first broken entry."""
    expected_prev_hash = GENESIS_PREV_HASH
    for idx, entry in enumerate(entries):
        expected_seq = idx + 1
        if entry.seq != expected_seq:
            return LedgerVerifyResponse(
                run_id=run_id,
                valid=False,
                total_entries=len(entries),
                first_broken_seq=entry.seq,
                failure_reason=f"Sequence gap at index {idx}: expected seq {expected_seq}, got {entry.seq}",
                entries=entries,
            )

        if entry.prev_hash != expected_prev_hash:
            return LedgerVerifyResponse(
                run_id=run_id,
                valid=False,
                total_entries=len(entries),
                first_broken_seq=entry.seq,
                failure_reason=(
                    f"Broken prev_hash link at seq {entry.seq}: "
                    f"expected {expected_prev_hash[:12]}..., got {entry.prev_hash[:12]}..."
                ),
                entries=entries,
            )

        recomputed_hash = compute_entry_hash(entry.prev_hash, entry.payload_json)
        if not hmac.compare_digest(recomputed_hash, entry.entry_hash):
            return LedgerVerifyResponse(
                run_id=run_id,
                valid=False,
                total_entries=len(entries),
                first_broken_seq=entry.seq,
                failure_reason=f"Entry hash mismatch at seq {entry.seq}: payload or hash was modified.",
                entries=entries,
            )

        recomputed_hmac = compute_hmac_signature(secret, entry.entry_hash, entry.seq, entry.run_id)
        if not hmac.compare_digest(recomputed_hmac, entry.hmac_signature):
            return LedgerVerifyResponse(
                run_id=run_id,
                valid=False,
                total_entries=len(entries),
                first_broken_seq=entry.seq,
                failure_reason=f"HMAC-SHA256 signature verification failed at seq {entry.seq}.",
                entries=entries,
            )

        expected_prev_hash = entry.entry_hash

    return LedgerVerifyResponse(
        run_id=run_id,
        valid=True,
        total_entries=len(entries),
        first_broken_seq=None,
        failure_reason=None,
        entries=entries,
    )
