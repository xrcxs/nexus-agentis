import React from 'react';
import type { SourceRecord } from '../types';

interface SourceTableProps {
  sources: SourceRecord[];
}

export const SourceTable: React.FC<SourceTableProps> = ({ sources }) => {
  return (
    <section
      aria-label="Retrieved Sources and Credibility Breakdown"
      className="rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4"
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400">
          Retrieved Sources & Transparent Credibility Heuristic ({sources.length})
        </h2>
      </div>

      {sources.length === 0 ? (
        <p className="text-xs font-mono text-slate-500 py-6 text-center">
          No sources retrieved yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 font-mono text-[11px]">
                <th className="py-2 px-2">ID</th>
                <th className="py-2 px-2">Section</th>
                <th className="py-2 px-2">Source & Canonical URL</th>
                <th className="py-2 px-2">Credibility</th>
                <th className="py-2 px-2">Heuristic Reasoning Breakdown</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {sources.map((s) => (
                <tr key={s.source_id} className="hover:bg-slate-800/40 align-top">
                  <td className="py-2.5 px-2 font-mono font-bold text-cyan-300">
                    [{s.source_id}]
                  </td>
                  <td className="py-2.5 px-2 font-mono text-slate-400">{s.section_id}</td>
                  <td className="py-2.5 px-2 max-w-xs">
                    <a
                      href={s.canonical_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-semibold text-cyan-200 hover:underline break-words"
                    >
                      {s.title}
                    </a>
                    <div className="text-[11px] font-mono text-slate-400 mt-0.5">
                      {s.domain} • {s.published_date ?? 'Date N/A'}
                    </div>
                  </td>
                  <td className="py-2.5 px-2 font-mono">
                    <span
                      className={`inline-block px-2 py-0.5 rounded font-bold ${
                        s.credibility_score >= 0.75
                          ? 'bg-lime-950/70 text-lime-300 border border-lime-500/40'
                          : s.credibility_score >= 0.6
                            ? 'bg-cyan-950/70 text-cyan-300 border border-cyan-500/40'
                            : 'bg-rose-950/70 text-rose-300 border border-rose-500/40'
                      }`}
                    >
                      {(s.credibility_score * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="py-2.5 px-2 font-mono text-[11px] text-slate-300 max-w-md">
                    {s.credibility_breakdown.reasoning}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
