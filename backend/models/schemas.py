"""Pydantic v2 data models and schemas for NEXUS//AGENTIS.

Uses native Pydantic v2 APIs (`ConfigDict`, `field_validator`, `model_validator`,
`model_dump`, `model_validate`) when Pydantic >= 2.0 is installed, with a transparent
bridge when executed under system Pydantic 1.10.x in offline sandbox containers.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Literal, TypeVar

import pydantic
from pydantic import BaseModel, Field

PYDANTIC_V2 = int(pydantic.__version__.split(".")[0]) >= 2

TModel = TypeVar("TModel", bound="NexusBaseModel")

if PYDANTIC_V2:
    from pydantic import ConfigDict, field_validator, model_validator

    class NexusBaseModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

else:
    from pydantic import Extra, root_validator, validator

    def field_validator(field_name: str) -> Callable[[Callable[..., Any]], Any]:  # type: ignore[misc]
        def _decorator(fn: Callable[..., Any]) -> Any:
            return validator(field_name, allow_reuse=True)(fn)

        return _decorator

    def model_validator(*, mode: str = "after") -> Callable[[Callable[..., Any]], Any]:  # type: ignore[misc]
        def _decorator(fn: Callable[..., Any]) -> Any:
            def _wrapped(cls: Any, values: dict[str, Any]) -> dict[str, Any]:
                instance = cls.construct(**values)
                fn(instance)
                return values

            return root_validator(pre=(mode == "before"), allow_reuse=True)(_wrapped)

        return _decorator

    class NexusBaseModel(BaseModel):
        class Config:
            extra = Extra.forbid

        def model_dump(self, **kwargs: Any) -> dict[str, Any]:
            return json.loads(self.json(**kwargs))

        def model_dump_json(self, **kwargs: Any) -> str:
            return self.json(**kwargs)

        @classmethod
        def model_validate(cls: type[TModel], obj: Any) -> TModel:
            return cls.parse_obj(obj)

        @classmethod
        def model_validate_json(cls: type[TModel], raw_json: str | bytes) -> TModel:
            return cls.parse_raw(raw_json)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    SYNTHESIZING = "synthesizing"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    PARTIAL_BUDGET_EXHAUSTED = "partial_budget_exhausted"
    REJECTED = "rejected"
    FAILED = "failed"


class ClaimVerdict(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class HumanAction(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class PlanSection(NexusBaseModel):
    section_id: str = Field(..., min_length=2, max_length=32, regex=r"^[a-zA-Z0-9_-]+$" if not PYDANTIC_V2 else None, pattern=r"^[a-zA-Z0-9_-]+$" if PYDANTIC_V2 else None)  # type: ignore[call-overload]
    title: str = Field(..., min_length=3, max_length=160)
    sub_question: str = Field(..., min_length=10, max_length=400)
    search_query: str = Field(..., min_length=5, max_length=250)


class ResearchPlan(NexusBaseModel):
    research_question: str = Field(..., min_length=5, max_length=1000)
    sections: list[PlanSection] = Field(..., min_items=4, max_items=4) if not PYDANTIC_V2 else Field(..., min_length=4, max_length=4)  # type: ignore[call-overload]

    @model_validator(mode="after")
    def validate_unique_section_ids(self) -> ResearchPlan:
        secs = getattr(self, "sections", None) or []
        ids = [s.section_id for s in secs]
        if len(ids) != 4 or len(set(ids)) != 4:
            raise ValueError("All 4 plan sections must have unique section_id values.")
        return self


class CredibilityBreakdown(NexusBaseModel):
    domain_class: Literal[
        "gov_edu_standards",
        "academic_journal",
        "established_tech_news",
        "general_web",
        "low_trust_or_ugc",
    ]
    domain_score: float = Field(..., ge=0.0, le=1.0)
    https_score: float = Field(..., ge=0.0, le=1.0)
    recency_score: float = Field(..., ge=0.0, le=1.0)
    tavily_relevance_score: float = Field(..., ge=0.0, le=1.0)
    composite_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., min_length=5)


class SourceRecord(NexusBaseModel):
    source_id: str = Field(..., regex=r"^S\d+$" if not PYDANTIC_V2 else None, pattern=r"^S\d+$" if PYDANTIC_V2 else None)  # type: ignore[call-overload]
    run_id: str
    section_id: str
    url: str
    canonical_url: str
    domain: str
    title: str
    snippet: str
    published_date: str | None = None
    tavily_score: float = Field(default=0.5, ge=0.0, le=1.0)
    credibility_score: float = Field(..., ge=0.0, le=1.0)
    credibility_breakdown: CredibilityBreakdown
    retrieved_at: str = Field(default_factory=utc_now_iso)


class ClaimRecord(NexusBaseModel):
    claim_id: str
    run_id: str
    section_id: str
    sentence: str
    cited_source_ids: list[str]
    primary_source_id: str
    verdict: ClaimVerdict
    quoted_evidence: str
    rationale: str
    loop_iteration: int = Field(default=0, ge=0)
    verified_at: str = Field(default_factory=utc_now_iso)


class SectionVerificationResult(NexusBaseModel):
    section_id: str
    title: str
    draft_markdown: str
    total_claims: int = Field(..., ge=0)
    supported_claims: int = Field(..., ge=0)
    partial_claims: int = Field(..., ge=0)
    unsupported_claims: int = Field(..., ge=0)
    supported_ratio: float = Field(..., ge=0.0, le=1.0)
    distinct_credible_sources: int = Field(..., ge=0)
    passed: bool
    low_confidence: bool = False
    loop_count: int = Field(default=0, ge=0)
    refined_query: str | None = None
    failure_reason: str | None = None


class CreateRunRequest(NexusBaseModel):
    question: str = Field(..., min_length=10, max_length=1000)
    token_budget: int = Field(default=32000, ge=2000, le=128000)
    max_loops: int = Field(default=3, ge=1, le=3)
    support_threshold: float = Field(default=0.75, ge=0.5, le=1.0)

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 10:
            raise ValueError("Research question must be at least 10 non-whitespace characters.")
        return cleaned


class HumanDecisionRequest(NexusBaseModel):
    action: HumanAction
    feedback: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_feedback_on_revise(self) -> HumanDecisionRequest:
        if self.action == HumanAction.REVISE and (not self.feedback or not self.feedback.strip()):
            raise ValueError("Feedback text is required when requesting a revision.")
        return self


class TokenUsageSummary(NexusBaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    budget_limit: int = 32000
    estimated_cost_usd: float = 0.0
    budget_exhausted: bool = False


class RunEvent(NexusBaseModel):
    event_id: int
    run_id: str
    node: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


class LedgerEntry(NexusBaseModel):
    seq: int
    run_id: str
    event_type: str
    node: str
    payload_json: str
    prev_hash: str
    entry_hash: str
    hmac_signature: str
    created_at: str


class LedgerVerifyResponse(NexusBaseModel):
    run_id: str
    scheme: Literal["tamper-evident-sha256-hmac"] = "tamper-evident-sha256-hmac"
    description: str = (
        "Tamper-evident hash chain + HMAC-SHA256 verification. Detects accidental corruption "
        "or unauthorized DB edits without the server HMAC secret; not tamper-proof against an "
        "attacker who holds the server secret and rewrites the entire chain."
    )
    valid: bool
    total_entries: int
    first_broken_seq: int | None = None
    failure_reason: str | None = None
    entries: list[LedgerEntry] = Field(default_factory=list)


class RunSummary(NexusBaseModel):
    run_id: str
    question: str
    status: RunStatus
    active_node: str | None
    token_usage: TokenUsageSummary
    max_loops: int
    current_loop: int
    support_threshold: float
    created_at: str
    updated_at: str
    error_message: str | None = None


class RunDetail(RunSummary):
    plan: ResearchPlan | None = None
    sections: list[SectionVerificationResult] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    report_markdown: str | None = None
    human_feedback: str | None = None


class ErrorResponse(NexusBaseModel):
    error_code: str
    message: str
    details: dict[str, Any] | None = None
