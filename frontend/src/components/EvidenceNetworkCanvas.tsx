import React, { useEffect, useRef } from 'react';
import type { ClaimRecord, SourceRecord } from '../types';

interface EvidenceNetworkCanvasProps {
  sources: SourceRecord[];
  claims: ClaimRecord[];
}

interface ForceNode {
  id: string;
  label: string;
  kind: 'source' | 'claim';
  verdict?: string;
  credibility?: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface ForceLink {
  source: string;
  target: string;
}

export const EvidenceNetworkCanvas: React.FC<EvidenceNetworkCanvasProps> = ({
  sources,
  claims,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const isVisibleRef = useRef<boolean>(true);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const prefersReducedMotion = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          isVisibleRef.current = entry.isIntersecting;
        });
      },
      { threshold: 0.05 },
    );
    observer.observe(canvas);

    const width = canvas.width;
    const height = canvas.height;

    const nodes: ForceNode[] = [
      ...sources.map((s, idx) => ({
        id: s.source_id,
        label: s.source_id,
        kind: 'source' as const,
        credibility: s.credibility_score,
        x: width * 0.25 + ((idx * 53) % (width * 0.5)),
        y: 40 + ((idx * 37) % (height - 80)),
        vx: 0,
        vy: 0,
      })),
      ...claims.map((c, idx) => ({
        id: c.claim_id,
        label: `C${idx + 1}`,
        kind: 'claim' as const,
        verdict: c.verdict,
        x: width * 0.3 + ((idx * 67) % (width * 0.45)),
        y: 45 + ((idx * 43) % (height - 90)),
        vx: 0,
        vy: 0,
      })),
    ];

    const nodeMap = new Map<string, ForceNode>(nodes.map((n) => [n.id, n]));
    const links: ForceLink[] = [];
    for (const c of claims) {
      for (const sid of c.cited_source_ids) {
        if (nodeMap.has(sid)) {
          links.push({ source: c.claim_id, target: sid });
        }
      }
    }

    let animId = 0;
    let ticks = 0;

    const stepPhysics = () => {
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x || 0.1;
          const dy = b.y - a.y || 0.1;
          const distSq = dx * dx + dy * dy + 40;
          const force = 420 / distSq;
          a.vx -= dx * force;
          a.vy -= dy * force;
          b.vx += dx * force;
          b.vy += dy * force;
        }
      }

      for (const link of links) {
        const s = nodeMap.get(link.source);
        const t = nodeMap.get(link.target);
        if (!s || !t) continue;
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const delta = (dist - 70) * 0.015;
        const fx = (dx / dist) * delta;
        const fy = (dy / dist) * delta;
        s.vx += fx;
        s.vy += fy;
        t.vx -= fx;
        t.vy -= fy;
      }

      for (const n of nodes) {
        n.vx = (n.vx + (width / 2 - n.x) * 0.002) * 0.82;
        n.vy = (n.vy + (height / 2 - n.y) * 0.002) * 0.82;
        n.x = Math.max(24, Math.min(width - 24, n.x + n.vx));
        n.y = Math.max(24, Math.min(height - 24, n.y + n.vy));
      }
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      for (const link of links) {
        const s = nodeMap.get(link.source);
        const t = nodeMap.get(link.target);
        if (!s || !t) continue;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.strokeStyle = 'rgba(0, 245, 212, 0.28)';
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }

      for (const n of nodes) {
        ctx.beginPath();
        const radius = n.kind === 'source' ? 11 : 8;
        ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
        if (n.kind === 'source') {
          ctx.fillStyle = '#00f5d4';
        } else if (n.verdict === 'supported') {
          ctx.fillStyle = '#39ff14';
        } else if (n.verdict === 'partial') {
          ctx.fillStyle = '#ffb703';
        } else {
          ctx.fillStyle = '#ff2a85';
        }
        ctx.fill();

        ctx.fillStyle = '#e2e8f0';
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(n.label, n.x, n.y - radius - 4);
      }
    };

    if (prefersReducedMotion) {
      for (let i = 0; i < 40; i++) stepPhysics();
      draw();
    } else {
      const renderLoop = () => {
        if (!document.hidden && isVisibleRef.current && ticks < 180) {
          stepPhysics();
          draw();
          ticks += 1;
        }
        animId = window.requestAnimationFrame(renderLoop);
      };
      draw();
      animId = window.requestAnimationFrame(renderLoop);
    }

    return () => {
      observer.disconnect();
      if (animId) window.cancelAnimationFrame(animId);
    };
  }, [sources, claims]);

  return (
    <section
      aria-label="Evidence Entailment Force Network"
      className="rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400">
          Evidence Entailment Network (Canvas Force Graph)
        </h2>
        <div className="flex items-center gap-3 text-[11px] font-mono">
          <span className="flex items-center gap-1 text-cyan-300">
            <span className="h-2.5 w-2.5 rounded-full bg-[#00f5d4]" /> Source [S#]
          </span>
          <span className="flex items-center gap-1 text-lime-300">
            <span className="h-2.5 w-2.5 rounded-full bg-[#39ff14]" /> Supported Claim
          </span>
          <span className="flex items-center gap-1 text-amber-300">
            <span className="h-2.5 w-2.5 rounded-full bg-[#ffb703]" /> Partial
          </span>
          <span className="flex items-center gap-1 text-rose-300">
            <span className="h-2.5 w-2.5 rounded-full bg-[#ff2a85]" /> Unsupported
          </span>
        </div>
      </div>

      {sources.length === 0 && claims.length === 0 ? (
        <div className="h-56 flex items-center justify-center text-xs font-mono text-slate-500 border border-slate-800 rounded-lg bg-[#05070e]">
          No sources or verified claims retrieved yet. Launch a run to populate the evidence graph.
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          width={640}
          height={240}
          className="w-full h-56 rounded-lg border border-slate-800 bg-[#05070e]"
        />
      )}
    </section>
  );
};
