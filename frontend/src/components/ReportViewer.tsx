import React, { useState } from 'react';

interface ReportViewerProps {
  runId: string | null;
  reportMarkdown: string | null;
}

export const ReportViewer: React.FC<ReportViewerProps> = ({ runId, reportMarkdown }) => {
  const [copied, setCopied] = useState(false);

  if (!reportMarkdown) {
    return null;
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(reportMarkdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([reportMarkdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${runId ?? 'nexus-report'}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section
      aria-label="Final Verified Research Report"
      data-testid="report-viewer"
      className="rounded-xl border border-lime-500/40 bg-slate-900/80 backdrop-blur-md p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="text-xs font-mono uppercase tracking-widest text-lime-300">
          Finalized Markdown Research Report
        </h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="px-3 py-1 rounded bg-slate-800 border border-slate-600 text-xs font-mono text-slate-200 hover:border-cyan-400"
          >
            {copied ? 'COPIED!' : 'COPY .MD'}
          </button>
          <button
            type="button"
            onClick={handleDownload}
            className="px-3 py-1 rounded bg-lime-500/20 border border-lime-400 text-xs font-mono text-lime-200 hover:bg-lime-500/30"
          >
            DOWNLOAD .MD
          </button>
        </div>
      </div>

      <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-800 bg-[#05070e] p-4 font-mono text-xs text-slate-200 max-h-[480px] overflow-y-auto">
        {reportMarkdown}
      </pre>
    </section>
  );
};
