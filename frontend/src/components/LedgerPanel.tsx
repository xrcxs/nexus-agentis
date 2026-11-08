import React from 'react';
import type { LedgerVerifyResponse } from '../types';

interface LedgerPanelProps {
  runId: string | null;
  verification: LedgerVerifyResponse | null;
  isVerifying: boolean;
  onVerify: () => Promise<void>;
}

export const LedgerPanel: React.FC<LedgerPanelProps> = ({
  runId,
  verification,
  isVerifying,
  onVerify,
}) => {
  return (
    <section
      aria-label="Tamper-Evident Cryptographic Ledger"
      className="rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400">
            Tamper-Evident Event Ledger (SHA-256 Chain + HMAC-SHA256)
          </h2>
          <p className="text-[11px] text-slate-400">
            Each entry chains <code className="text-cyan-300">sha256(prev_hash + canonical_json(event))</code>{' '}
            and an HMAC-SHA256 server signature. Tamper-evident, never claimed as tamper-proof.
          </p>
        </div>

        <button
          type="button"
          disabled={!runId || isVerifying}
          data-testid="verify-ledger-btn"
          onClick={() => void onVerify()}
          className="px-3 py-1.5 rounded-lg bg-cyan-500/20 border border-cyan-400 text-cyan-200 font-mono text-xs font-bold hover:bg-cyan-500/30 disabled:opacity-40"
        >
          {isVerifying ? 'VERIFYING...' : 'VERIFY CHAIN'}
        </button>
      </div>

      {verification && (
        <div className="space-y-3">
          <div
            data-testid="ledger-verify-banner"
            className={`p-3 rounded-lg border font-mono text-xs ${
              verification.valid
                ? 'bg-lime-950/40 border-lime-500/50 text-lime-200'
                : 'bg-rose-950/40 border-rose-500/60 text-rose-200'
            }`}
          >
            {verification.valid ? (
              <span>
                CHAIN INTEGRITY VERIFIED: All {verification.total_entries} entries matched
                recomputed SHA-256 links and HMAC-SHA256 signatures.
              </span>
            ) : (
              <span>
                TAMPER DETECTED AT SEQ #{verification.first_broken_seq}:{' '}
                {verification.failure_reason}
              </span>
            )}
          </div>

          <div className="max-h-52 overflow-y-auto rounded-lg border border-slate-800 bg-[#05070e] font-mono text-[11px]">
            <table className="w-full text-left border-collapse">
              <thead className="sticky top-0 bg-slate-900 text-slate-400">
                <tr>
                  <th className="py-1.5 px-2">Seq</th>
                  <th className="py-1.5 px-2">Node / Event</th>
                  <th className="py-1.5 px-2">Prev Hash</th>
                  <th className="py-1.5 px-2">Entry Hash</th>
                  <th className="py-1.5 px-2">HMAC-SHA256</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {verification.entries.map((entry) => (
                  <tr key={entry.seq} className="hover:bg-slate-900/60">
                    <td className="py-1.5 px-2 text-cyan-300">#{entry.seq}</td>
                    <td className="py-1.5 px-2 text-slate-200">
                      {entry.node} :: {entry.event_type}
                    </td>
                    <td className="py-1.5 px-2 text-slate-500">{entry.prev_hash.slice(0, 12)}…</td>
                    <td className="py-1.5 px-2 text-lime-300">{entry.entry_hash.slice(0, 12)}…</td>
                    <td className="py-1.5 px-2 text-fuchsia-300">
                      {entry.hmac_signature.slice(0, 12)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
};
