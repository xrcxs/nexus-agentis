"""Evaluation harness (`make eval`) running 10 fixed research questions through NEXUS//AGENTIS.

Measures real pipeline execution metrics:
- Citation validity rate (%)
- Supported-claim ratio (%)
- Average tokens per run (prompt + completion)
- Average latency per run (ms)
- Tamper-evident ledger verification rate (%)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.app.config import Settings
from backend.graph.workflow import RunOrchestrator
from backend.models.schemas import ClaimVerdict, HumanAction, RunStatus
from backend.services.database import Database
from backend.services.verifier import CITATION_TAG_RE

EVAL_QUESTIONS: list[str] = [
    "How do speculative decoding algorithms accelerate autoregressive LLM inference while preserving output distributions?",
    "What are the throughput and memory trade-offs between PagedAttention and FlashAttention-3 in long-context serving?",
    "How do Byzantine fault-tolerant consensus protocols compare in message complexity and WAN tail latency?",
    "What cryptographic guarantees and threat models differentiate tamper-evident hash chains from RFC 6962 Certificate Transparency logs?",
    "How does retrieval-augmented generation with claim-level entailment verification reduce factual hallucination rates?",
    "What are the empirical scaling laws for Mixture-of-Experts routing load balance and all-to-all communication overhead?",
    "How do eBPF-based L7 service meshes compare to sidecar proxies in CPU utilization and p99 packet latency?",
    "What are the security boundaries and SSRF mitigation techniques for autonomous web-browsing agent architectures?",
    "How do quantized KV-cache compression methods affect perplexity and multi-hop reasoning accuracy in 70B models?",
    "What fault-tolerance mechanisms enable durable stateful agent execution across process restarts in SQLite-backed workflows?",
]


async def run_evaluation() -> dict[str, Any]:
    use_live = bool(os.environ.get("GROQ_API_KEY") and os.environ.get("TAVILY_API_KEY")) and (
        os.environ.get("NEXUS_STUB_APIS", "false").lower() not in ("1", "true", "yes")
    )
    mode_label = "live_groq_tavily" if use_live else "recorded_fixture_benchmark"

    per_question_results: list[dict[str, Any]] = []
    total_citations = 0
    valid_citations = 0
    total_claims = 0
    supported_claims = 0
    total_tokens_all = 0
    latencies_ms: list[float] = []
    ledger_valid_count = 0

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            database_path=os.path.join(tmp, "eval_runs.db"),
            checkpoint_db_path=os.path.join(tmp, "eval_ckpt.db"),
            stub_external_apis=not use_live,
            rate_limit_rpm=6000 if not use_live else 30,
        )
        db = Database(settings.database_path, settings.ledger_secret)
        orchestrator = RunOrchestrator(settings=settings, db=db)

        for idx, question in enumerate(EVAL_QUESTIONS, start=1):
            run_id = f"eval_run_{idx:02d}"
            t0 = time.perf_counter()
            db.create_run(
                run_id=run_id,
                question=question,
                token_budget=32000,
                max_loops=3,
                support_threshold=0.75,
            )
            await orchestrator.execute_run(run_id)
            await orchestrator.resume_from_human_gate(run_id, action=HumanAction.APPROVE)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            latencies_ms.append(elapsed_ms)

            detail = db.get_run_detail(run_id)
            assert detail is not None
            assert detail.status == RunStatus.COMPLETED

            source_ids = {s.source_id for s in detail.sources}
            run_cites = 0
            run_valid_cites = 0
            for sec in detail.sections:
                tags = CITATION_TAG_RE.findall(sec.draft_markdown)
                for tag in tags:
                    run_cites += 1
                    total_citations += 1
                    if tag in source_ids:
                        run_valid_cites += 1
                        valid_citations += 1

            run_claims = len(detail.claims)
            run_supported = sum(1 for c in detail.claims if c.verdict == ClaimVerdict.SUPPORTED)
            total_claims += run_claims
            supported_claims += run_supported
            total_tokens_all += detail.token_usage.total_tokens

            ledger_check = db.verify_run_ledger(run_id)
            if ledger_check.valid:
                ledger_valid_count += 1

            per_question_results.append(
                {
                    "id": idx,
                    "run_id": run_id,
                    "question": question,
                    "status": detail.status.value,
                    "sources_count": len(detail.sources),
                    "claims_count": run_claims,
                    "supported_claims": run_supported,
                    "supported_claim_ratio": round(run_supported / max(1, run_claims), 4),
                    "citations_count": run_cites,
                    "valid_citations_count": run_valid_cites,
                    "citation_validity_rate": round(run_valid_cites / max(1, run_cites), 4),
                    "total_tokens": detail.token_usage.total_tokens,
                    "latency_ms": elapsed_ms,
                    "ledger_valid": ledger_check.valid,
                }
            )

    summary = {
        "mode": mode_label,
        "questions_evaluated": len(EVAL_QUESTIONS),
        "citation_validity_rate": round((valid_citations / max(1, total_citations)) * 100.0, 2),
        "supported_claim_ratio": round((supported_claims / max(1, total_claims)) * 100.0, 2),
        "average_tokens_per_run": round(total_tokens_all / len(EVAL_QUESTIONS), 1),
        "average_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2),
        "ledger_verification_pass_rate": round((ledger_valid_count / len(EVAL_QUESTIONS)) * 100.0, 2),
        "total_claims_verified": total_claims,
        "total_citations_checked": total_citations,
        "runs": per_question_results,
    }

    eval_dir = Path(__file__).resolve().parent
    (eval_dir / "eval_results.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("=" * 78)
    print(f"NEXUS//AGENTIS EVALUATION BENCHMARK ({summary['questions_evaluated']} QUESTIONS)")
    print(f"Execution Mode              : {summary['mode']}")
    print("-" * 78)
    print(f"Citation Validity Rate      : {summary['citation_validity_rate']:.2f}% ({valid_citations}/{total_citations})")
    print(f"Supported-Claim Ratio       : {summary['supported_claim_ratio']:.2f}% ({supported_claims}/{total_claims})")
    print(f"Average Tokens per Run      : {summary['average_tokens_per_run']} tokens")
    print(f"Average Latency per Run     : {summary['average_latency_ms']} ms")
    print(f"Ledger Integrity Pass Rate  : {summary['ledger_verification_pass_rate']:.2f}% ({ledger_valid_count}/{len(EVAL_QUESTIONS)})")
    print("=" * 78)
    return summary


if __name__ == "__main__":
    asyncio.run(run_evaluation())
