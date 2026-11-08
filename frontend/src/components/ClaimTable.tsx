import React from 'react';
import type { ClaimRecord } from '../types';

interface ClaimTableProps {
  claims: ClaimRecord[];
}

export const ClaimTable: React.FC<ClaimTableProps> = ({ claims }) => {
  return (
    <section
      aria-label="Verified Claims and Quoted Evidence"
      className="rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4"
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400">
          Claim-by-Claim Entailment Verification ({claims.length})
        </h2>
      </div>

      {claims.length === 0 ? (
        <p className="text-xs font-mono text-slate-500 py-6 text-center">
          No claims verified yet.
        </p>
      ) : (
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-900">
              <tr className="border-b border-slate-800 text-slate-400 font-mono text-[11px]">
                <th className="py-2 px-2">Verdict</th>
                <th className="py-2 px-2">Section</th>
                <th className="py-2 px-2">Claim Sentence</th>
                <th className="py-2 px-2">Citations</th>
                <th className="py-2 px-2">Quoted Supporting Evidence & Rationale</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {claims.map((c) => {
                const badgeClass =
                  c.verdict === 'supported'
                    ? 'bg-lime-950/80 text-lime-300 border-lime-500/50'
                    : c.verdict === 'partial'
                      ? 'bg-amber-950/80 text-amber-300 border-amber-500/50'
                      : 'bg-rose-950/80 text-rose-300 border-rose-500/50';
                return (
                  <tr key={c.claim_id} className="hover:bg-slate-800/40 align-top">
                    <td className="py-2.5 px-2 font-mono">
                      <span
                        className={`inline-block px-2 py-0.5 rounded border text-[10px] uppercase font-bold ${badgeClass}`}
                      >
                        {c.verdict}
                      </span>
                    </td>
                    <td className="py-2.5 px-2 font-mono text-slate-400">{c.section_id}</td>
                    <td className="py-2.5 px-2 text-slate-100 max-w-md">{c.sentence}</td>
                    <td className="py-2.5 px-2 font-mono text-cyan-300">
                      {c.cited_source_ids.map((id) => `[${id}]`).join(' ')}
                    </td>
                    <td className="py-2.5 px-2 max-w-md">
                      <blockquote className="border-l-2 border-cyan-500/60 pl-2 italic text-slate-300 text-[11px]">
                        "{c.quoted_evidence}"
                      </blockquote>
                      <div className="text-[11px] text-slate-400 mt-1">{c.rationale}</div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
