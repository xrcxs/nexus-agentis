import { create } from 'zustand';
import { apiClient } from '../api/client';
import type {
  HumanAction,
  LedgerVerifyResponse,
  RunDetail,
  RunEvent,
  RunSummary,
} from '../types';

interface RunStoreState {
  runs: RunSummary[];
  activeRunId: string | null;
  activeRun: RunDetail | null;
  events: RunEvent[];
  lastEventId: number;
  ledgerVerification: LedgerVerifyResponse | null;
  isLoading: boolean;
  isSubmittingDecision: boolean;
  isVerifyingLedger: boolean;
  error: string | null;

  fetchRuns: () => Promise<void>;
  selectRun: (runId: string) => Promise<void>;
  launchRun: (params: {
    question: string;
    token_budget: number;
    max_loops: number;
    support_threshold: number;
  }) => Promise<void>;
  ingestEventBatch: (incoming: RunEvent[]) => void;
  submitHumanDecision: (action: HumanAction, feedback?: string) => Promise<void>;
  verifyActiveLedger: () => Promise<void>;
  clearError: () => void;
}

export const useRunStore = create<RunStoreState>((set, get) => ({
  runs: [],
  activeRunId: null,
  activeRun: null,
  events: [],
  lastEventId: 0,
  ledgerVerification: null,
  isLoading: false,
  isSubmittingDecision: false,
  isVerifyingLedger: false,
  error: null,

  clearError: () => set({ error: null }),

  fetchRuns: async () => {
    try {
      const runs = await apiClient.listRuns();
      set({ runs });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to load runs' });
    }
  },

  selectRun: async (runId: string) => {
    set({
      activeRunId: runId,
      isLoading: true,
      error: null,
      events: [],
      lastEventId: 0,
      ledgerVerification: null,
    });
    try {
      const detail = await apiClient.getRunDetail(runId);
      set({ activeRun: detail, isLoading: false });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to load run details',
      });
    }
  },

  launchRun: async (params) => {
    set({ isLoading: true, error: null, events: [], lastEventId: 0, ledgerVerification: null });
    try {
      const summary = await apiClient.createRun(params);
      const detail = await apiClient.getRunDetail(summary.run_id);
      set((state) => ({
        runs: [summary, ...state.runs.filter((r) => r.run_id !== summary.run_id)],
        activeRunId: summary.run_id,
        activeRun: detail,
        isLoading: false,
      }));
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to start research run',
      });
    }
  },

  ingestEventBatch: (incoming: RunEvent[]) => {
    if (incoming.length === 0) return;
    set((state) => {
      const existingIds = new Set(state.events.map((e) => e.event_id));
      const deduped = incoming.filter((e) => !existingIds.has(e.event_id));
      if (deduped.length === 0) return state;

      const merged = [...state.events, ...deduped].sort((a, b) => a.event_id - b.event_id);
      const maxId = merged[merged.length - 1]?.event_id ?? state.lastEventId;

      let updatedRun = state.activeRun ? { ...state.activeRun } : null;
      for (const ev of deduped) {
        if (!updatedRun || ev.run_id !== updatedRun.run_id) continue;
        if (ev.event_type === 'node_started') {
          updatedRun.active_node = ev.node;
        } else if (ev.event_type === 'token_usage_updated') {
          updatedRun.token_usage = {
            prompt_tokens: Number(ev.payload.prompt_tokens ?? updatedRun.token_usage.prompt_tokens),
            completion_tokens: Number(
              ev.payload.completion_tokens ?? updatedRun.token_usage.completion_tokens,
            ),
            total_tokens: Number(ev.payload.total_tokens ?? updatedRun.token_usage.total_tokens),
            budget_limit: Number(ev.payload.budget_limit ?? updatedRun.token_usage.budget_limit),
            estimated_cost_usd: Number(
              ev.payload.estimated_cost_usd ?? updatedRun.token_usage.estimated_cost_usd,
            ),
            budget_exhausted: Boolean(
              ev.payload.budget_exhausted ?? updatedRun.token_usage.budget_exhausted,
            ),
          };
        } else if (ev.event_type === 'awaiting_human_decision') {
          updatedRun.status = 'awaiting_approval';
          updatedRun.active_node = 'human_gate';
        } else if (ev.event_type === 'run_completed') {
          updatedRun.status = 'completed';
          updatedRun.active_node = null;
        }
      }

      return {
        events: merged,
        lastEventId: maxId,
        activeRun: updatedRun,
      };
    });

    const activeId = get().activeRunId;
    if (activeId) {
      void apiClient
        .getRunDetail(activeId)
        .then((detail) => {
          if (get().activeRunId === activeId) {
            set({ activeRun: detail });
          }
        })
        .catch(() => {
          // Ignore transient refresh error during active streaming
        });
    }
  },

  submitHumanDecision: async (action: HumanAction, feedback?: string) => {
    const runId = get().activeRunId;
    if (!runId) return;
    set({ isSubmittingDecision: true, error: null });
    try {
      const updated = await apiClient.submitDecision(runId, { action, feedback });
      set({ activeRun: updated, isSubmittingDecision: false });
      await get().fetchRuns();
    } catch (err) {
      set({
        isSubmittingDecision: false,
        error: err instanceof Error ? err.message : 'Failed to submit decision',
      });
    }
  },

  verifyActiveLedger: async () => {
    const runId = get().activeRunId;
    if (!runId) return;
    set({ isVerifyingLedger: true, error: null });
    try {
      const res = await apiClient.verifyLedger(runId);
      set({ ledgerVerification: res, isVerifyingLedger: false });
    } catch (err) {
      set({
        isVerifyingLedger: false,
        error: err instanceof Error ? err.message : 'Ledger verification failed',
      });
    }
  },
}));
