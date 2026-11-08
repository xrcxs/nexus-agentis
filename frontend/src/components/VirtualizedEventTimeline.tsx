import React, { useState } from 'react';
import type { RunEvent } from '../types';

interface VirtualizedEventTimelineProps {
  events: RunEvent[];
}

const ROW_HEIGHT = 44;
const VIEWPORT_HEIGHT = 240;

export const VirtualizedEventTimeline: React.FC<VirtualizedEventTimelineProps> = ({
  events,
}) => {
  const [scrollTop, setScrollTop] = useState(0);

  const totalHeight = events.length * ROW_HEIGHT;
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 2);
  const visibleCount = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + 4;
  const endIndex = Math.min(events.length, startIndex + visibleCount);
  const visibleEvents = events.slice(startIndex, endIndex);

  return (
    <section
      aria-label="Live SSE Event Stream"
      className="rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400">
          Live SSE Event Stream (Virtualized)
        </h2>
        <span className="text-xs font-mono text-slate-400">
          {events.length} persisted events
        </span>
      </div>

      {events.length === 0 ? (
        <div className="h-[240px] flex items-center justify-center text-xs font-mono text-slate-500 border border-slate-800 rounded-lg bg-[#05070e]">
          Awaiting SSE telemetry frames...
        </div>
      ) : (
        <div
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
          style={{ height: VIEWPORT_HEIGHT }}
          className="overflow-y-auto rounded-lg border border-slate-800 bg-[#05070e] font-mono text-xs relative"
        >
          <div style={{ height: totalHeight, position: 'relative' }}>
            {visibleEvents.map((ev, idx) => {
              const top = (startIndex + idx) * ROW_HEIGHT;
              return (
                <div
                  key={ev.event_id}
                  style={{ top, height: ROW_HEIGHT }}
                  className="absolute left-0 right-0 px-3 flex items-center justify-between border-b border-slate-800/70 hover:bg-slate-900/80"
                >
                  <div className="flex items-center gap-2 truncate pr-2">
                    <span className="text-slate-500">#{ev.event_id}</span>
                    <span className="px-1.5 py-0.5 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-500/30 text-[10px]">
                      {ev.node}
                    </span>
                    <span className="text-slate-200 font-semibold">{ev.event_type}</span>
                    <span className="text-slate-400 truncate text-[11px]">
                      {JSON.stringify(ev.payload)}
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-500 shrink-0">
                    {ev.created_at.slice(11, 19)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
};
