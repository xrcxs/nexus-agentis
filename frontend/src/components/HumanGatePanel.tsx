import React, { useState } from 'react';
import type { HumanAction, RunStatus } from '../types';

interface HumanGatePanelProps {
  status: RunStatus | null;
  isSubmitting: boolean;
  onDecision: (action: HumanAction, feedback?: string) => Promise<void>;
}

export const HumanGatePanel: React.FC<HumanGatePanelProps> = ({
  status,
  isSubmitting,
  onDecision,
}) => {
  const [feedback, setFeedback] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  if (status !== 'awaiting_approval') {
    return null;
  }

  const handleAction = async (action: HumanAction) => {
    if (action === 'revise' && !feedback.trim()) {
      setLocalError('Please provide revision feedback before requesting a loop back.');
      return;
    }
    setLocalError(null);
    await onDecision(action, feedback.trim() || undefined);
  };

  return (
    <section
      aria-label="Human Approval Interrupt Gate"
      data-testid="human-gate-panel"
      className="rounded-xl border-2 border-fuchsia-500/70 bg-fuchsia-950/20 backdrop-blur-md p-4 shadow-[0_0_25px_rgba(255,42,133,0.2)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <h2 className="text-xs font-mono uppercase tracking-widest text-fuchsia-300 font-bold">
          // LANGGRAPH INTERRUPT: HUMAN APPROVAL GATE ACTIVE
        </h2>
        <span className="text-[11px] font-mono text-fuchsia-200 px-2 py-0.5 rounded bg-fuchsia-900/50">
          Checkpoint Persisted in SQLite (Resumable Across Server Restart)
        </span>
      </div>

      <p className="text-xs text-slate-300 mb-3">
        Inspect the verified claims and source credibility scores below. You may approve the run to
        compile the final Markdown report, request a targeted revision loop with feedback, or reject
        the run.
      </p>

      <div className="space-y-3">
        <div>
          <label
            htmlFor="human-feedback-input"
            className="block text-[11px] font-mono text-slate-300 mb-1"
          >
            Reviewer Feedback (Required for Revision)
          </label>
          <textarea
            id="human-feedback-input"
            rows={2}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g., Expand section 2 with additional peer-reviewed latency benchmarks..."
            className="w-full rounded-lg border border-slate-700 bg-slate-950/90 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
          />
          {localError && <p className="text-xs text-rose-400 mt-1 font-mono">{localError}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={isSubmitting}
            data-testid="approve-run-btn"
            onClick={() => void handleAction('approve')}
            className="px-4 py-2 rounded-lg bg-lime-500/20 border border-lime-400 text-lime-200 font-mono text-xs font-bold hover:bg-lime-500/30 disabled:opacity-50"
          >
            {isSubmitting ? 'PROCESSING...' : 'APPROVE & FINALIZE REPORT'}
          </button>

          <button
            type="button"
            disabled={isSubmitting}
            data-testid="revise-run-btn"
            onClick={() => void handleAction('revise')}
            className="px-4 py-2 rounded-lg bg-cyan-500/20 border border-cyan-400 text-cyan-200 font-mono text-xs font-bold hover:bg-cyan-500/30 disabled:opacity-50"
          >
            REQUEST REVISION LOOP
          </button>

          <button
            type="button"
            disabled={isSubmitting}
            data-testid="reject-run-btn"
            onClick={() => void handleAction('reject')}
            className="px-4 py-2 rounded-lg bg-rose-500/20 border border-rose-500 text-rose-200 font-mono text-xs font-bold hover:bg-rose-500/30 disabled:opacity-50"
          >
            REJECT RUN
          </button>
        </div>
      </div>
    </section>
  );
};
