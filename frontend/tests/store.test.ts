import { describe, it, expect, beforeEach } from 'vitest';
import { useRunStore } from '../src/store/useRunStore';
import type { RunEvent } from '../src/types';

describe('useRunStore SSE event ingestion & deduplication', () => {
  beforeEach(() => {
    useRunStore.setState({
      runs: [],
      activeRunId: 'run_test_1',
      activeRun: {
        run_id: 'run_test_1',
        question: 'Test question for store verification',
        status: 'planning',
        active_node: 'planner',
        token_usage: {
          prompt_tokens: 0,
          completion_tokens: 0,
          total_tokens: 0,
          budget_limit: 16000,
          estimated_cost_usd: 0,
          budget_exhausted: false,
        },
        max_loops: 3,
        current_loop: 0,
        support_threshold: 0.75,
        created_at: '2026-11-06T00:00:00Z',
        updated_at: '2026-11-06T00:00:00Z',
        error_message: null,
        plan: null,
        sections: [],
        sources: [],
        claims: [],
        report_markdown: null,
        human_feedback: null,
      },
      events: [],
      lastEventId: 0,
      ledgerVerification: null,
      isLoading: false,
      isSubmittingDecision: false,
      isVerifyingLedger: false,
      error: null,
    });
  });

  it('deduplicates incoming SSE events and updates token accounting and active node', () => {
    const batch: RunEvent[] = [
      {
        event_id: 1,
        run_id: 'run_test_1',
        node: 'retriever',
        event_type: 'node_started',
        payload: {},
        created_at: '2026-11-06T00:00:01Z',
      },
      {
        event_id: 2,
        run_id: 'run_test_1',
        node: 'accounting',
        event_type: 'token_usage_updated',
        payload: {
          prompt_tokens: 210,
          completion_tokens: 265,
          total_tokens: 475,
          budget_limit: 16000,
          estimated_cost_usd: 0.000333,
          budget_exhausted: false,
        },
        created_at: '2026-11-06T00:00:02Z',
      },
    ];

    useRunStore.getState().ingestEventBatch(batch);
    // Ingest duplicate event_id 1
    useRunStore.getState().ingestEventBatch([batch[0]]);

    const state = useRunStore.getState();
    expect(state.events).toHaveLength(2);
    expect(state.lastEventId).toBe(2);
    expect(state.activeRun?.active_node).toBe('retriever');
    expect(state.activeRun?.token_usage.total_tokens).toBe(475);
  });
});
