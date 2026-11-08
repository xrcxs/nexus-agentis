export type RunStatus =
  | 'queued'
  | 'planning'
  | 'retrieving'
  | 'synthesizing'
  | 'verifying'
  | 'awaiting_approval'
  | 'finalizing'
  | 'completed'
  | 'partial_budget_exhausted'
  | 'rejected'
  | 'failed';

export type ClaimVerdict = 'supported' | 'partial' | 'unsupported';

export type HumanAction = 'approve' | 'revise' | 'reject';

export interface PlanSection {
  section_id: string;
  title: string;
  sub_question: string;
  search_query: string;
}

export interface ResearchPlan {
  research_question: string;
  sections: PlanSection[];
}

export interface CredibilityBreakdown {
  domain_class:
    | 'gov_edu_standards'
    | 'academic_journal'
    | 'established_tech_news'
    | 'general_web'
    | 'low_trust_or_ugc';
  domain_score: number;
  https_score: number;
  recency_score: number;
  tavily_relevance_score: number;
  composite_score: number;
  reasoning: string;
}

export interface SourceRecord {
  source_id: string;
  run_id: string;
  section_id: string;
  url: string;
  canonical_url: string;
  domain: string;
  title: string;
  snippet: string;
  published_date: string | null;
  tavily_score: number;
  credibility_score: number;
  credibility_breakdown: CredibilityBreakdown;
  retrieved_at: string;
}

export interface ClaimRecord {
  claim_id: string;
  run_id: string;
  section_id: string;
  sentence: string;
  cited_source_ids: string[];
  primary_source_id: string;
  verdict: ClaimVerdict;
  quoted_evidence: string;
  rationale: string;
  loop_iteration: number;
  verified_at: string;
}

export interface SectionVerificationResult {
  section_id: string;
  title: string;
  draft_markdown: string;
  total_claims: number;
  supported_claims: number;
  partial_claims: number;
  unsupported_claims: number;
  supported_ratio: number;
  distinct_credible_sources: number;
  passed: boolean;
  low_confidence: boolean;
  loop_count: number;
  refined_query: string | null;
  failure_reason: string | null;
}

export interface TokenUsageSummary {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  budget_limit: number;
  estimated_cost_usd: number;
  budget_exhausted: boolean;
}

export interface RunEvent {
  event_id: number;
  run_id: string;
  node: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface LedgerEntry {
  seq: number;
  run_id: string;
  event_type: string;
  node: string;
  payload_json: string;
  prev_hash: string;
  entry_hash: string;
  hmac_signature: string;
  created_at: string;
}

export interface LedgerVerifyResponse {
  run_id: string;
  scheme: 'tamper-evident-sha256-hmac';
  description: string;
  valid: boolean;
  total_entries: number;
  first_broken_seq: number | null;
  failure_reason: string | null;
  entries: LedgerEntry[];
}

export interface RunSummary {
  run_id: string;
  question: string;
  status: RunStatus;
  active_node: string | null;
  token_usage: TokenUsageSummary;
  max_loops: number;
  current_loop: number;
  support_threshold: number;
  created_at: string;
  updated_at: string;
  error_message: string | null;
}

export interface RunDetail extends RunSummary {
  plan: ResearchPlan | null;
  sections: SectionVerificationResult[];
  sources: SourceRecord[];
  claims: ClaimRecord[];
  report_markdown: string | null;
  human_feedback: string | null;
}
