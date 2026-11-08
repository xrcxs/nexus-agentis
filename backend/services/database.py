"""SQLite storage layer for runs, events, sources, claims, and the tamper-evident ledger."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from backend.models.schemas import (
    ClaimRecord,
    ClaimVerdict,
    CredibilityBreakdown,
    LedgerEntry,
    LedgerVerifyResponse,
    ResearchPlan,
    RunDetail,
    RunEvent,
    RunStatus,
    RunSummary,
    SectionVerificationResult,
    SourceRecord,
    TokenUsageSummary,
    utc_now_iso,
)
from backend.services.ledger import GENESIS_PREV_HASH, build_ledger_entry, verify_ledger_chain


class Database:
    """Thread-safe SQLite repository for NEXUS//AGENTIS."""

    def __init__(self, db_path: str, ledger_secret: str) -> None:
        self.db_path = db_path
        self._ledger_secret = ledger_secret
        self._lock = threading.RLock()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._persistent_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
        self.init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._persistent_conn is not None:
                yield self._persistent_conn
                self._persistent_conn.commit()
            else:
                conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                except sqlite3.OperationalError:
                    conn.execute("PRAGMA journal_mode=MEMORY;")
                conn.execute("PRAGMA foreign_keys=ON;")
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_node TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    budget_limit INTEGER NOT NULL DEFAULT 32000,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                    budget_exhausted INTEGER NOT NULL DEFAULT 0,
                    max_loops INTEGER NOT NULL DEFAULT 3,
                    current_loop INTEGER NOT NULL DEFAULT 0,
                    support_threshold REAL NOT NULL DEFAULT 0.75,
                    plan_json TEXT,
                    sections_json TEXT NOT NULL DEFAULT '[]',
                    report_markdown TEXT,
                    human_feedback TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    node TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id, event_id);

                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    published_date TEXT,
                    tavily_score REAL NOT NULL,
                    credibility_score REAL NOT NULL,
                    credibility_breakdown_json TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, source_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_sources_run_id ON sources(run_id);

                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    sentence TEXT NOT NULL,
                    cited_source_ids_json TEXT NOT NULL,
                    primary_source_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    quoted_evidence TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    loop_iteration INTEGER NOT NULL DEFAULT 0,
                    verified_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, claim_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_claims_run_id ON claims(run_id);

                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seq INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    node TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL,
                    hmac_signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (run_id, seq),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_ledger_run_seq ON ledger(run_id, seq);
                """
            )

    def create_run(
        self,
        *,
        run_id: str,
        question: str,
        token_budget: int,
        max_loops: int,
        support_threshold: float,
    ) -> RunSummary:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, question, status, active_node, budget_limit,
                    max_loops, current_loop, support_threshold, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    run_id,
                    question,
                    RunStatus.QUEUED.value,
                    "planner",
                    token_budget,
                    max_loops,
                    support_threshold,
                    now,
                    now,
                ),
            )
        self.append_event(
            run_id=run_id,
            node="system",
            event_type="run_created",
            payload={
                "question": question,
                "token_budget": token_budget,
                "max_loops": max_loops,
                "support_threshold": support_threshold,
            },
        )
        summary = self.get_run_summary(run_id)
        assert summary is not None
        return summary

    def append_event(
        self,
        *,
        run_id: str,
        node: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> RunEvent:
        """Atomically record a live event and append a chained HMAC entry to the ledger."""
        now = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (run_id, node, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, node, event_type, json.dumps(payload, sort_keys=True), now),
            )
            event_id = int(cursor.lastrowid or 0)

            last_row = conn.execute(
                "SELECT seq, entry_hash FROM ledger WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if last_row is None:
                next_seq = 1
                prev_hash = GENESIS_PREV_HASH
            else:
                next_seq = int(last_row["seq"]) + 1
                prev_hash = str(last_row["entry_hash"])

            ledger_entry = build_ledger_entry(
                seq=next_seq,
                run_id=run_id,
                node=node,
                event_type=event_type,
                payload=payload,
                prev_hash=prev_hash,
                secret=self._ledger_secret,
                created_at=now,
            )
            conn.execute(
                """
                INSERT INTO ledger (
                    seq, run_id, event_type, node, payload_json,
                    prev_hash, entry_hash, hmac_signature, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ledger_entry.seq,
                    ledger_entry.run_id,
                    ledger_entry.event_type,
                    ledger_entry.node,
                    ledger_entry.payload_json,
                    ledger_entry.prev_hash,
                    ledger_entry.entry_hash,
                    ledger_entry.hmac_signature,
                    ledger_entry.created_at,
                ),
            )
            conn.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )

        return RunEvent(
            event_id=event_id,
            run_id=run_id,
            node=node,
            event_type=event_type,
            payload=payload,
            created_at=now,
        )

    def update_run_state(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        active_node: str | None = "__UNSET__",
        current_loop: int | None = None,
        plan: ResearchPlan | None = None,
        sections: list[SectionVerificationResult] | None = None,
        report_markdown: str | None = None,
        human_feedback: str | None = None,
        error_message: str | None = None,
    ) -> None:
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [utc_now_iso()]

        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
        if active_node != "__UNSET__":
            updates.append("active_node = ?")
            params.append(active_node)
        if current_loop is not None:
            updates.append("current_loop = ?")
            params.append(current_loop)
        if plan is not None:
            updates.append("plan_json = ?")
            params.append(plan.model_dump_json())
        if sections is not None:
            updates.append("sections_json = ?")
            params.append(json.dumps([s.model_dump() for s in sections]))
        if report_markdown is not None:
            updates.append("report_markdown = ?")
            params.append(report_markdown)
        if human_feedback is not None:
            updates.append("human_feedback = ?")
            params.append(human_feedback)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        params.append(run_id)
        sql = f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?"
        with self._connect() as conn:
            conn.execute(sql, params)

    def record_token_usage(
        self,
        run_id: str,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        budget_exhausted: bool = False,
    ) -> TokenUsageSummary:
        """Increment real token counts from Groq response usage and calculate cost ($0.59/$0.79 per 1M)."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT prompt_tokens, completion_tokens, budget_limit, budget_exhausted
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Run {run_id} not found")

            new_prompt = int(row["prompt_tokens"]) + prompt_tokens
            new_completion = int(row["completion_tokens"]) + completion_tokens
            new_total = new_prompt + new_completion
            budget_limit = int(row["budget_limit"])
            exhausted = bool(row["budget_exhausted"]) or budget_exhausted or (new_total >= budget_limit)
            cost_usd = round((new_prompt * 0.59 + new_completion * 0.79) / 1_000_000, 6)

            conn.execute(
                """
                UPDATE runs
                SET prompt_tokens = ?, completion_tokens = ?, total_tokens = ?,
                    estimated_cost_usd = ?, budget_exhausted = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    new_prompt,
                    new_completion,
                    new_total,
                    cost_usd,
                    1 if exhausted else 0,
                    utc_now_iso(),
                    run_id,
                ),
            )
            return TokenUsageSummary(
                prompt_tokens=new_prompt,
                completion_tokens=new_completion,
                total_tokens=new_total,
                budget_limit=budget_limit,
                estimated_cost_usd=cost_usd,
                budget_exhausted=exhausted,
            )

    def save_sources(self, run_id: str, sources: list[SourceRecord]) -> None:
        with self._connect() as conn:
            for src in sources:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sources (
                        source_id, run_id, section_id, url, canonical_url, domain,
                        title, snippet, published_date, tavily_score,
                        credibility_score, credibility_breakdown_json, retrieved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        src.source_id,
                        run_id,
                        src.section_id,
                        src.url,
                        src.canonical_url,
                        src.domain,
                        src.title,
                        src.snippet,
                        src.published_date,
                        src.tavily_score,
                        src.credibility_score,
                        src.credibility_breakdown.model_dump_json(),
                        src.retrieved_at,
                    ),
                )

    def replace_section_claims(self, run_id: str, section_id: str, claims: list[ClaimRecord]) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM claims WHERE run_id = ? AND section_id = ?",
                (run_id, section_id),
            )
            for claim in claims:
                conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, run_id, section_id, sentence, cited_source_ids_json,
                        primary_source_id, verdict, quoted_evidence, rationale,
                        loop_iteration, verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim.claim_id,
                        run_id,
                        claim.section_id,
                        claim.sentence,
                        json.dumps(claim.cited_source_ids),
                        claim.primary_source_id,
                        claim.verdict.value,
                        claim.quoted_evidence,
                        claim.rationale,
                        claim.loop_iteration,
                        claim.verified_at,
                    ),
                )

    def _row_to_summary(self, row: sqlite3.Row) -> RunSummary:
        return RunSummary(
            run_id=str(row["run_id"]),
            question=str(row["question"]),
            status=RunStatus(str(row["status"])),
            active_node=row["active_node"],
            token_usage=TokenUsageSummary(
                prompt_tokens=int(row["prompt_tokens"]),
                completion_tokens=int(row["completion_tokens"]),
                total_tokens=int(row["total_tokens"]),
                budget_limit=int(row["budget_limit"]),
                estimated_cost_usd=float(row["estimated_cost_usd"]),
                budget_exhausted=bool(row["budget_exhausted"]),
            ),
            max_loops=int(row["max_loops"]),
            current_loop=int(row["current_loop"]),
            support_threshold=float(row["support_threshold"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            error_message=row["error_message"],
        )

    def get_run_summary(self, run_id: str) -> RunSummary | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return self._row_to_summary(row) if row is not None else None

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_summary(r) for r in rows]

    def get_sources(self, run_id: str) -> list[SourceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sources WHERE run_id = ? ORDER BY CAST(SUBSTR(source_id, 2) AS INTEGER) ASC",
                (run_id,),
            ).fetchall()
            result: list[SourceRecord] = []
            for r in rows:
                result.append(
                    SourceRecord(
                        source_id=str(r["source_id"]),
                        run_id=str(r["run_id"]),
                        section_id=str(r["section_id"]),
                        url=str(r["url"]),
                        canonical_url=str(r["canonical_url"]),
                        domain=str(r["domain"]),
                        title=str(r["title"]),
                        snippet=str(r["snippet"]),
                        published_date=r["published_date"],
                        tavily_score=float(r["tavily_score"]),
                        credibility_score=float(r["credibility_score"]),
                        credibility_breakdown=CredibilityBreakdown.model_validate_json(
                            str(r["credibility_breakdown_json"])
                        ),
                        retrieved_at=str(r["retrieved_at"]),
                    )
                )
            return result

    def get_claims(self, run_id: str) -> list[ClaimRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM claims WHERE run_id = ? ORDER BY claim_id ASC",
                (run_id,),
            ).fetchall()
            return [
                ClaimRecord(
                    claim_id=str(r["claim_id"]),
                    run_id=str(r["run_id"]),
                    section_id=str(r["section_id"]),
                    sentence=str(r["sentence"]),
                    cited_source_ids=json.loads(str(r["cited_source_ids_json"])),
                    primary_source_id=str(r["primary_source_id"]),
                    verdict=ClaimVerdict(str(r["verdict"])),
                    quoted_evidence=str(r["quoted_evidence"]),
                    rationale=str(r["rationale"]),
                    loop_iteration=int(r["loop_iteration"]),
                    verified_at=str(r["verified_at"]),
                )
                for r in rows
            ]

    def get_run_detail(self, run_id: str) -> RunDetail | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            summary = self._row_to_summary(row)
            plan = (
                ResearchPlan.model_validate_json(str(row["plan_json"]))
                if row["plan_json"]
                else None
            )
            raw_sections = json.loads(str(row["sections_json"] or "[]"))
            sections = [SectionVerificationResult.model_validate(s) for s in raw_sections]

        sources = self.get_sources(run_id)
        claims = self.get_claims(run_id)
        return RunDetail(
            **summary.model_dump(),
            plan=plan,
            sections=sections,
            sources=sources,
            claims=claims,
            report_markdown=row["report_markdown"],
            human_feedback=row["human_feedback"],
        )

    def get_events_since(self, run_id: str, last_event_id: int = 0) -> list[RunEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, run_id, node, event_type, payload_json, created_at
                FROM events
                WHERE run_id = ? AND event_id > ?
                ORDER BY event_id ASC
                """,
                (run_id, last_event_id),
            ).fetchall()
            return [
                RunEvent(
                    event_id=int(r["event_id"]),
                    run_id=str(r["run_id"]),
                    node=str(r["node"]),
                    event_type=str(r["event_type"]),
                    payload=json.loads(str(r["payload_json"])),
                    created_at=str(r["created_at"]),
                )
                for r in rows
            ]

    def get_ledger_entries(self, run_id: str) -> list[LedgerEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq, run_id, event_type, node, payload_json,
                       prev_hash, entry_hash, hmac_signature, created_at
                FROM ledger
                WHERE run_id = ?
                ORDER BY seq ASC
                """,
                (run_id,),
            ).fetchall()
            return [
                LedgerEntry(
                    seq=int(r["seq"]),
                    run_id=str(r["run_id"]),
                    event_type=str(r["event_type"]),
                    node=str(r["node"]),
                    payload_json=str(r["payload_json"]),
                    prev_hash=str(r["prev_hash"]),
                    entry_hash=str(r["entry_hash"]),
                    hmac_signature=str(r["hmac_signature"]),
                    created_at=str(r["created_at"]),
                )
                for r in rows
            ]

    def verify_run_ledger(self, run_id: str) -> LedgerVerifyResponse:
        entries = self.get_ledger_entries(run_id)
        return verify_ledger_chain(run_id, entries, self._ledger_secret)
