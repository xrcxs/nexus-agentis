import type {
  HumanAction,
  LedgerVerifyResponse,
  RunDetail,
  RunSummary,
} from '../types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '/api';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let errMessage = `HTTP ${response.status}`;
    try {
      const errBody = (await response.json()) as { message?: string };
      if (errBody.message) {
        errMessage = errBody.message;
      }
    } catch {
      // Fallback to status code message
    }
    throw new Error(errMessage);
  }
  return (await response.json()) as T;
}

export const apiClient = {
  baseUrl: API_BASE,

  listRuns(): Promise<RunSummary[]> {
    return requestJson<RunSummary[]>('/runs');
  },

  createRun(params: {
    question: string;
    token_budget: number;
    max_loops: number;
    support_threshold: number;
  }): Promise<RunSummary> {
    return requestJson<RunSummary>('/runs', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  getRunDetail(runId: string): Promise<RunDetail> {
    return requestJson<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
  },

  submitDecision(
    runId: string,
    decision: { action: HumanAction; feedback?: string },
  ): Promise<RunDetail> {
    return requestJson<RunDetail>(`/runs/${encodeURIComponent(runId)}/decision`, {
      method: 'POST',
      body: JSON.stringify(decision),
    });
  },

  verifyLedger(runId: string): Promise<LedgerVerifyResponse> {
    return requestJson<LedgerVerifyResponse>(
      `/runs/${encodeURIComponent(runId)}/ledger/verify`,
    );
  },

  async getReportMarkdown(runId: string): Promise<string> {
    const response = await fetch(
      `${API_BASE}/runs/${encodeURIComponent(runId)}/report.md`,
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch report Markdown (HTTP ${response.status})`);
    }
    return response.text();
  },
};
