import React, { useEffect, useRef, useState } from 'react';
import { apiClient } from './api/client';
import { useRunStore } from './store/useRunStore';
import { AgentGraphPanel } from './components/AgentGraphPanel';
import { EvidenceNetworkCanvas } from './components/EvidenceNetworkCanvas';
import { VirtualizedEventTimeline } from './components/VirtualizedEventTimeline';
import { SourceTable } from './components/SourceTable';
import { ClaimTable } from './components/ClaimTable';
import { HumanGatePanel } from './components/HumanGatePanel';
import { LedgerPanel } from './components/LedgerPanel';
import { ReportViewer } from './components/ReportViewer';
import type { RunEvent } from './types';

export const App: React.FC = () => {
  const {
    runs,
    activeRunId,
    activeRun,
    events,
    lastEventId,
    ledgerVerification,
    isLoading,
    isSubmittingDecision,
    isVerifyingLedger,
    error,
    fetchRuns,
    selectRun,
    launchRun,
    ingestEventBatch,
    submitHumanDecision,
    verifyActiveLedger,
    clearError,
  } = useRunStore();

  const [question, setQuestion] = useState(
    'How do speculative decoding algorithms accelerate autoregressive LLM inference while guaranteeing lossless output distributions?',
  );
  const [tokenBudget, setTokenBudget] = useState(24000);
  const [maxLoops, setMaxLoops] = useState(3);
  const [supportThreshold, setSupportThreshold] = useState(0.75);

  const eventBufferRef = useRef<RunEvent[]>([]);

  useEffect(() => {
    void fetchRuns();
  }, [fetchRuns]);

  // Throttled SSE stream subscription with Last-Event-ID resume support
  useEffect(() => {
    if (!activeRunId) return;

    const currentLastId = useRunStore.getState().lastEventId;
    const streamUrl = `${apiClient.baseUrl}/runs/${encodeURIComponent(
      activeRunId,
    )}/events?last_event_id=${currentLastId}`;
    const es = new EventSource(streamUrl);

    const handleFrame = (evt: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(evt.data) as RunEvent;
        eventBufferRef.current.push(parsed);
      } catch {
        // Ignore malformed SSE comment/frame
      }
    };

    const eventTypes = [
      'run_created',
      'node_started',
      'plan_completed',
      'plan_validation_retry',
      'section_sources_retrieved',
      'retrieval_completed',
      'section_synthesized',
      'citation_guard_retry',
      'section_verified',
      'section_flagged_low_confidence',
      'loop_back_triggered',
      'awaiting_human_decision',
      'human_decision_received',
      'token_usage_updated',
      'budget_exhausted_partial_released',
      'run_completed',
      'run_failed',
    ];
    for (const t of eventTypes) {
      es.addEventListener(t, handleFrame as EventListener);
    }

    const flushTimer = window.setInterval(() => {
      if (eventBufferRef.current.length > 0) {
        const batch = eventBufferRef.current.splice(0, eventBufferRef.current.length);
        ingestEventBatch(batch);
      }
    }, 120);

    return () => {
      window.clearInterval(flushTimer);
      es.close();
    };
  }, [activeRunId, activeRun?.status]);

  const handleLaunch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim().length < 10) return;
    await launchRun({
      question: question.trim(),
      token_budget: tokenBudget,
      max_loops: maxLoops,
      support_threshold: supportThreshold,
    });
  };

  const usage = activeRun?.token_usage;
  const budgetPct = usage
    ? Math.min(100, Math.round((usage.total_tokens / Math.max(1, usage.budget_limit)) * 100))
    : 0;

  return (
    <div className="min-h-screen px-3 py-4 sm:px-6 max-w-[1440px] mx-auto space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-cyan-500/30 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-cyan-400 animate-pulse" />
            <h1 className="font-mono text-lg sm:text-xl font-extrabold tracking-wider text-cyan-300">
              NEXUS // AGENTIS
            </h1>
          </div>
          <p className="text-xs text-slate-400">
            Autonomous Multi-Agent Research Graph • Claim-Level Entailment Verifier • Tamper-Evident Ledger
          </p>
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="run-history-select" className="text-xs font-mono text-slate-400">
            Run History:
          </label>
          <select
            id="run-history-select"
            aria-label="Select historical research run"
            value={activeRunId ?? ''}
            onChange={(e) => {
              if (e.target.value) void selectRun(e.target.value);
            }}
            className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-cyan-200"
          >
            <option value="">-- Select Run ({runs.length}) --</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id} [{r.status}] — {r.question.slice(0, 42)}…
              </option>
            ))}
          </select>
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-rose-500/60 bg-rose-950/50 p-3 flex items-center justify-between text-xs font-mono text-rose-200"
        >
          <span>ERROR: {error}</span>
          <button
            type="button"
            onClick={clearError}
            className="underline ml-4 text-rose-300 hover:text-white"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Run Launcher + Real Token Accounting Meter */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <form
          onSubmit={(e) => void handleLaunch(e)}
          className="lg:col-span-2 rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4 space-y-3"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400">
              Launch Research Mission
            </h2>
            <span className="text-[11px] font-mono text-slate-400">
              Groq llama-3.3-70b-versatile + Tavily Search
            </span>
          </div>

          <div>
            <label htmlFor="question-input" className="block text-xs font-mono text-slate-300 mb-1">
              Research Question
            </label>
            <input
              id="question-input"
              data-testid="question-input"
              type="text"
              required
              minLength={10}
              maxLength={1000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label htmlFor="budget-input" className="block text-[11px] font-mono text-slate-400">
                Token Budget Limit
              </label>
              <input
                id="budget-input"
                type="number"
                min={2000}
                max={128000}
                step={1000}
                value={tokenBudget}
                onChange={(e) => setTokenBudget(Number(e.target.value))}
                className="w-full mt-1 rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-cyan-200"
              />
            </div>

            <div>
              <label htmlFor="loops-input" className="block text-[11px] font-mono text-slate-400">
                Max Verifier Loops (1-3)
              </label>
              <input
                id="loops-input"
                type="number"
                min={1}
                max={3}
                value={maxLoops}
                onChange={(e) => setMaxLoops(Number(e.target.value))}
                className="w-full mt-1 rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-cyan-200"
              />
            </div>

            <div>
              <label htmlFor="threshold-input" className="block text-[11px] font-mono text-slate-400">
                Support Ratio Gate
              </label>
              <input
                id="threshold-input"
                type="number"
                min={0.5}
                max={1.0}
                step={0.05}
                value={supportThreshold}
                onChange={(e) => setSupportThreshold(Number(e.target.value))}
                className="w-full mt-1 rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-cyan-200"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            data-testid="launch-run-btn"
            className="w-full sm:w-auto px-5 py-2 rounded-lg bg-cyan-500/20 border border-cyan-400 text-cyan-200 font-mono text-xs font-bold tracking-wider hover:bg-cyan-500/30 disabled:opacity-50"
          >
            {isLoading ? 'INITIALIZING GRAPH...' : 'DEPLOY AGENT GRAPH //'}
          </button>
        </form>

        {/* Real Token & Cost Accounting Meter */}
        <section
          aria-label="Real Token and Cost Accounting Meter"
          className="rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4 flex flex-col justify-between"
        >
          <div>
            <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400 mb-2">
              Token Budget & Cost Guard (Real API Usage)
            </h2>
            <div className="grid grid-cols-2 gap-2 font-mono text-xs">
              <div className="p-2 rounded bg-slate-950/80 border border-slate-800">
                <div className="text-[10px] text-slate-400">PROMPT TOKENS</div>
                <div className="text-sm font-bold text-cyan-300">{usage?.prompt_tokens ?? 0}</div>
              </div>
              <div className="p-2 rounded bg-slate-950/80 border border-slate-800">
                <div className="text-[10px] text-slate-400">COMPLETION TOKENS</div>
                <div className="text-sm font-bold text-cyan-300">
                  {usage?.completion_tokens ?? 0}
                </div>
              </div>
              <div className="p-2 rounded bg-slate-950/80 border border-slate-800">
                <div className="text-[10px] text-slate-400">TOTAL / BUDGET</div>
                <div className="text-sm font-bold text-slate-100">
                  {usage?.total_tokens ?? 0} / {usage?.budget_limit ?? tokenBudget}
                </div>
              </div>
              <div className="p-2 rounded bg-slate-950/80 border border-slate-800">
                <div className="text-[10px] text-slate-400">EST. COST (USD)</div>
                <div className="text-sm font-bold text-lime-300">
                  ${(usage?.estimated_cost_usd ?? 0).toFixed(6)}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-3">
            <div className="flex justify-between text-[11px] font-mono text-slate-400 mb-1">
              <span>Budget Utilization</span>
              <span>{budgetPct}%</span>
            </div>
            <div className="h-2.5 w-full rounded-full bg-slate-950 overflow-hidden border border-slate-800">
              <div
                style={{ width: `${budgetPct}%` }}
                className={`h-full transition-all ${
                  usage?.budget_exhausted
                    ? 'bg-rose-500'
                    : budgetPct > 80
                      ? 'bg-amber-400'
                      : 'bg-cyan-400'
                }`}
              />
            </div>
          </div>
        </section>
      </div>

      {/* Human Gate Interrupt Panel */}
      <HumanGatePanel
        status={activeRun?.status ?? null}
        isSubmitting={isSubmittingDecision}
        onDecision={submitHumanDecision}
      />

      {/* Live Agent Graph */}
      <AgentGraphPanel
        activeNode={activeRun?.active_node ?? null}
        status={activeRun?.status ?? null}
        currentLoop={activeRun?.current_loop ?? 0}
        maxLoops={activeRun?.max_loops ?? maxLoops}
      />

      {/* Evidence Force Network + Virtualized Event Stream */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EvidenceNetworkCanvas
          sources={activeRun?.sources ?? []}
          claims={activeRun?.claims ?? []}
        />
        <VirtualizedEventTimeline events={events} />
      </div>

      {/* Source Credibility Table & Claim Entailment Table */}
      <SourceTable sources={activeRun?.sources ?? []} />
      <ClaimTable claims={activeRun?.claims ?? []} />

      {/* Tamper-Evident Ledger Viewer */}
      <LedgerPanel
        runId={activeRunId}
        verification={ledgerVerification}
        isVerifying={isVerifyingLedger}
        onVerify={verifyActiveLedger}
      />

      {/* Finalized Report Viewer */}
      <ReportViewer
        runId={activeRunId}
        reportMarkdown={activeRun?.report_markdown ?? null}
      />
    </div>
  );
};
