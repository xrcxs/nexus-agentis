# ADR 002: Tamper-Evident SHA-256 + HMAC-SHA256 Event Ledger

## Status
Accepted

## Context
Audit logs for autonomous agent decisions, token accounting, and human approvals can be silently altered if stored as plain relational rows.

## Decision
Every event appended to the `ledger` table computes:
1. `entry_hash = sha256(prev_hash + canonical_json(event))` where seq 1 uses a 64-zero genesis `prev_hash`.
2. `hmac_signature = HMAC_SHA256(NEXUS_LEDGER_SECRET, f"{seq}:{run_id}:{entry_hash}")`.

The `GET /runs/{id}/ledger/verify` endpoint recomputes the entire chain from genesis and uses constant-time `hmac.compare_digest` to report the exact `first_broken_seq` if any payload, link, or signature was modified.

## Consequences
- **Honest Security Boundary:** This design is **tamper-evident**, never claimed as "tamper-proof". It detects accidental corruption and unauthorized SQLite edits by anyone lacking `NEXUS_LEDGER_SECRET`, but an adversary with root access to both the SQLite file and the environment secret could recompute the entire chain unless hashes are anchored to an external append-only witness.
