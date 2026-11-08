"""Recorded/stubbed test and offline-eval fixtures for Groq and Tavily responses."""
from __future__ import annotations

import json
import re
from typing import Any


def stub_tavily_search(section_id: str, query: str) -> list[dict[str, Any]]:
    """Deterministic recorded search snippets per section for testing and offline evaluation."""
    q_slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:36] or section_id
    is_refined = "empirical data peer reviewed benchmark" in query.lower()

    base_results = [
        {
            "url": f"https://arxiv.org/abs/2401.{abs(hash(section_id + '1')) % 89999 + 10000}?utm_source=tavily",
            "title": f"Empirical Architecture & Latency Analysis for {section_id.upper()}",
            "content": (
                f"Benchmark measurements for {section_id} demonstrate a 2.4x throughput increase "
                f"and a 38% reduction in p99 tail latency across 70B parameter transformer workloads. "
                f"Controlled ablation experiments confirm zero degradation in output distribution quality."
            ),
            "published_date": "2025-02-14",
            "score": 0.94,
        },
        {
            "url": f"https://www.nist.gov/publications/{section_id}-verification-standard-2025",
            "title": f"NIST Technical Standard: Verification & Safety Controls for {section_id.upper()}",
            "content": (
                f"Formal verification standards for {section_id} require cryptographic hash chaining, "
                f"deterministic schema validation, and explicit source entailment checks exceeding a 75% "
                f"supported-claim threshold across at least two independent high-credibility domains."
            ),
            "published_date": "2025-01-20",
            "score": 0.91,
        },
        {
            "url": f"https://ieee.org/document/{section_id}-{q_slug[:18]}",
            "title": f"IEEE Systems Review: Production Scaling & Fault Tolerance in {section_id.upper()}",
            "content": (
                f"Production deployments of {section_id} under burst traffic utilize token-bucket rate "
                f"limiting, exponential backoff with jitter on HTTP 429 responses, and strict token budget "
                f"accounting to prevent cascading resource exhaustion."
            ),
            "published_date": "2024-11-08",
            "score": 0.88,
        },
    ]

    if is_refined:
        base_results.append(
            {
                "url": f"https://dl.acm.org/doi/10.1145/{section_id}.refined.2025",
                "title": f"ACM Supplemental Benchmark Evidence for {section_id.upper()}",
                "content": (
                    f"Supplemental peer-reviewed benchmarks for {section_id} verify that multi-hop "
                    f"retrieval refinement raises claim entailment accuracy from 68% to 94% within two iterations."
                ),
                "published_date": "2025-03-01",
                "score": 0.95,
            }
        )

    return base_results


def stub_groq_responder(messages: list[dict[str, str]], json_mode: bool) -> dict[str, Any]:
    """Deterministic recorded OpenAI-compatible Groq payload for tests and offline evaluation."""
    system_prompt = messages[0]["content"] if messages else ""
    user_prompt = messages[-1]["content"] if messages else ""

    if "4-section research plan" in system_prompt or '"sections"' in system_prompt:
        question_match = re.search(r"Research Question:\s*(.+)", user_prompt)
        question = question_match.group(1).strip() if question_match else "Autonomous Multi-Agent Systems"
        plan_obj = {
            "research_question": question,
            "sections": [
                {
                    "section_id": "sec_1",
                    "title": "Core Algorithmic Foundations & Throughput Benchmarks",
                    "sub_question": f"What are the primary algorithmic mechanisms and latency benchmarks for: {question[:90]}?",
                    "search_query": f"{question[:100]} architecture latency throughput benchmark arxiv",
                },
                {
                    "section_id": "sec_2",
                    "title": "Verification Standards & Entailment Guarantees",
                    "sub_question": f"How are factual accuracy and cryptographic auditability enforced in: {question[:90]}?",
                    "search_query": f"{question[:100]} verification entailment standard nist",
                },
                {
                    "section_id": "sec_3",
                    "title": "Production Resilience, Rate Limiting & Cost Accounting",
                    "sub_question": f"What fault-tolerance and token budget controls govern production deployment of: {question[:90]}?",
                    "search_query": f"{question[:100]} rate limiting backoff token budget ieee",
                },
                {
                    "section_id": "sec_4",
                    "title": "Operational Trade-offs & Empirical Limitations",
                    "sub_question": f"What are the measured operational trade-offs and edge-case failure modes of: {question[:90]}?",
                    "search_query": f"{question[:100]} trade-offs limitations ablation study",
                },
            ],
        }
        content = json.dumps(plan_obj)
        return {
            "model": "llama-3.3-70b-versatile",
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 210, "completion_tokens": 265, "total_tokens": 475},
        }

    if "strict factual entailment verifier" in system_prompt:
        claim_match = re.search(r"Claim sentence:\s*(.+)", user_prompt)
        claim_text = claim_match.group(1).strip() if claim_match else ""
        snippet_match = re.search(r"<untrusted_source[^>]*>\s*(.+?)\s*</untrusted_source>", user_prompt, re.DOTALL)
        snippet_text = snippet_match.group(1).strip() if snippet_match else "Empirical benchmark evidence."
        first_sentence = snippet_text.split(".")[0].strip() + "."

        if "UNSUPPORTED_TEST_CLAIM" in claim_text:
            verdict_obj = {
                "verdict": "unsupported",
                "quoted_evidence": "",
                "rationale": "The cited snippet does not contain evidence supporting this claim.",
            }
        else:
            verdict_obj = {
                "verdict": "supported",
                "quoted_evidence": first_sentence,
                "rationale": "The cited snippet directly states the quantitative benchmark and mechanism described in the claim.",
            }
        return {
            "model": "llama-3.3-70b-versatile",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(verdict_obj)}}],
            "usage": {"prompt_tokens": 185, "completion_tokens": 68, "total_tokens": 253},
        }

    source_ids = re.findall(r'<untrusted_source id="(S\d+)"', user_prompt)
    s1 = source_ids[0] if len(source_ids) >= 1 else "S1"
    s2 = source_ids[1] if len(source_ids) >= 2 else s1
    s3 = source_ids[2] if len(source_ids) >= 3 else s2

    section_prose = (
        f"Controlled benchmark evaluations demonstrate a 2.4x throughput increase and a 38% reduction in p99 tail latency across 70B parameter transformer workloads [{s1}]. "
        f"Formal verification standards mandate cryptographic hash chaining, deterministic schema validation, and explicit source entailment checks exceeding a 75% supported-claim threshold across at least two independent credible domains [{s2}]. "
        f"Production deployments under burst traffic apply token-bucket rate limiting, exponential backoff with jitter on HTTP 429 responses, and strict token budget accounting to prevent cascading resource exhaustion [{s3}, {s1}]."
    )
    return {
        "model": "llama-3.3-70b-versatile",
        "choices": [{"message": {"role": "assistant", "content": section_prose}}],
        "usage": {"prompt_tokens": 340, "completion_tokens": 145, "total_tokens": 485},
    }
