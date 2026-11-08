# ADR 003: Claim-Level Entailment Verifier & Hard Loop Cutoff

## Status
Accepted

## Context
Standard RAG pipelines often cite retrieved URLs that do not actually support the sentence's factual claim, or hallucinate `[S#]` indices outside the retrieved set.

## Decision
We enforce a two-stage verification gate:
1. **Syntactic Citation Guard (`parse_claims_and_citations`):** Every declarative sentence in synthesized prose must carry at least one `[S#]` tag, and every cited ID must exist in the run's retrieved source table. Violations trigger an immediate synthesizer retry.
2. **Semantic LLM Entailment Gate (`verify_section_claims`):** Each `(sentence, cited_snippets)` pair is evaluated by the verifier with temperature `0.0` to return `supported | partial | unsupported` plus an exact `quoted_evidence` substring. A section passes only if `supported_ratio >= support_threshold` (default `0.75`) AND `distinct_credible_sources >= 2` (credibility `>= 0.60`). Failing sections loop back to `retriever` with a refined query up to `max_loops = 3`, after which they are explicitly flagged `low_confidence = True` in both the UI and final Markdown report.
