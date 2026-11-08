import React, { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  MarkerType,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { RunStatus } from '../types';

interface AgentGraphPanelProps {
  activeNode: string | null;
  status: RunStatus | null;
  currentLoop: number;
  maxLoops: number;
}

const PIPELINE_STEPS = [
  { id: 'planner', label: '01 // PLANNER', subtitle: '4-Section JSON Plan', x: 20, y: 80 },
  { id: 'retriever', label: '02 // RETRIEVER', subtitle: 'Tavily + Credibility', x: 220, y: 80 },
  { id: 'synthesizer', label: '03 // SYNTHESIZER', subtitle: 'Strict [S#] Grounding', x: 420, y: 80 },
  { id: 'verifier', label: '04 // VERIFIER', subtitle: 'Entailment Gate', x: 620, y: 80 },
  { id: 'human_gate', label: '05 // HUMAN GATE', subtitle: 'SqliteSaver Interrupt', x: 820, y: 80 },
  { id: 'finalizer', label: '06 // FINALIZER', subtitle: 'Markdown + Ledger', x: 1020, y: 80 },
];

export const AgentGraphPanel: React.FC<AgentGraphPanelProps> = ({
  activeNode,
  status,
  currentLoop,
  maxLoops,
}) => {
  const nodes: Node[] = useMemo(() => {
    return PIPELINE_STEPS.map((step) => {
      const isCurrent = activeNode === step.id;
      const isDone = status === 'completed';
      const borderColor = isCurrent
        ? '#00f5d4'
        : isDone
          ? '#39ff14'
          : 'rgba(0, 245, 212, 0.28)';
      const boxShadow = isCurrent
        ? '0 0 18px rgba(0, 245, 212, 0.55)'
        : 'none';

      return {
        id: step.id,
        position: { x: step.x, y: step.y },
        data: {
          label: (
            <div className="text-left font-mono">
              <div className="text-[11px] font-bold tracking-wider text-cyan-300">
                {step.label}
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5">{step.subtitle}</div>
            </div>
          ),
        },
        style: {
          background: 'rgba(13, 19, 34, 0.92)',
          border: `1.5px solid ${borderColor}`,
          borderRadius: '8px',
          padding: '8px 10px',
          width: 170,
          boxShadow,
          color: '#f1f5f9',
        },
      };
    });
  }, [activeNode, status]);

  const edges: Edge[] = useMemo(() => {
    const forwardEdges: Edge[] = [
      ['planner', 'retriever'],
      ['retriever', 'synthesizer'],
      ['synthesizer', 'verifier'],
      ['verifier', 'human_gate'],
      ['human_gate', 'finalizer'],
    ].map(([source, target]) => ({
      id: `e-${source}-${target}`,
      source,
      target,
      animated: activeNode === source || activeNode === target,
      style: { stroke: '#00f5d4', strokeWidth: 1.8 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#00f5d4' },
    }));

    const loopEdge: Edge = {
      id: 'e-verifier-retriever-loop',
      source: 'verifier',
      target: 'retriever',
      label: `Weak Section Loop (${currentLoop}/${maxLoops})`,
      animated: currentLoop > 0 && (activeNode === 'verifier' || activeNode === 'retriever'),
      style: { stroke: '#ff2a85', strokeWidth: 1.8, strokeDasharray: '5 4' },
      labelStyle: { fill: '#ff2a85', fontSize: 10, fontFamily: 'JetBrains Mono' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#ff2a85' },
    };

    return [...forwardEdges, loopEdge];
  }, [activeNode, currentLoop, maxLoops]);

  return (
    <section
      aria-label="Live LangGraph Agent Pipeline"
      className="rounded-xl border border-cyan-500/30 bg-slate-900/75 backdrop-blur-md p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <h2 className="text-xs font-mono uppercase tracking-widest text-cyan-400">
            LangGraph Execution Topology
          </h2>
          <p className="text-xs text-slate-400">
            Active Node:{' '}
            <span className="font-mono text-cyan-200">{activeNode ?? 'IDLE / TERMINAL'}</span>
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs font-mono">
          <span className="px-2.5 py-1 rounded bg-fuchsia-950/60 border border-fuchsia-500/40 text-fuchsia-300">
            REFINEMENT LOOPS: {currentLoop} / {maxLoops}
          </span>
          <span className="px-2.5 py-1 rounded bg-cyan-950/60 border border-cyan-500/40 text-cyan-300">
            STATUS: {status ? status.toUpperCase() : 'NO ACTIVE RUN'}
          </span>
        </div>
      </div>

      <div className="h-48 w-full rounded-lg border border-slate-800 bg-[#05070e] overflow-hidden">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={20} />
        </ReactFlow>
      </div>
    </section>
  );
};
