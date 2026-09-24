"use client";

import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { buildRingGraph, type RingNode } from "@/lib/ringData";
import type { CaseAnswer } from "@/lib/types";

/* A genuinely interactive force layout for the HHG-014 device ring, built without
   d3-force or react-force-graph: repulsion + spring + centring + damping, run in rAF,
   stopped once kinetic energy settles so it never burns a frame budget mid-recording.

   Positions seed from a deterministic PRNG so the same case renders the same ring on
   every load — a judge revisiting it should recognise it, exactly like CaseGraphView's
   own "organic but reproducible" rule. Edges curve toward the hub so 17 cards bundle
   instead of crosshatching, reusing CaseGraphView's trick. */

const W = 820;
const H = 520;
const CX = W / 2;
const CY = H / 2;

// mulberry32 — tiny, deterministic, no dependency.
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type SimNode = RingNode & {
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx: number | null; // pinned position while dragging
  fy: number | null;
  r: number;
};

const RADIUS: Record<RingNode["kind"], number> = {
  device: 28,
  "flagged-card": 15,
  "ring-card": 10,
};

function seedPositions(nodes: RingNode[]): SimNode[] {
  const rand = mulberry32(140);
  return nodes.map((n) => {
    const angle = rand() * Math.PI * 2;
    const dist = n.kind === "device" ? 0 : 90 + rand() * 160;
    return {
      ...n,
      x: CX + Math.cos(angle) * dist,
      y: CY + Math.sin(angle) * dist,
      vx: 0,
      vy: 0,
      fx: null,
      fy: null,
      r: RADIUS[n.kind],
    };
  });
}

// One tick of the simulation. Mutates positions in place for speed; returns total
// kinetic energy so the caller can decide whether to keep animating.
function tick(nodes: SimNode[], edges: { from: string; to: string }[], byId: Map<string, SimNode>) {
  const REPULSION = 2600;
  const SPRING = 0.02;
  const SPRING_LEN = 120;
  const CENTER = 0.008;
  const DAMPING = 0.82;

  for (const n of nodes) {
    if (n.fx != null) continue;
    n.vx += (CX - n.x) * CENTER;
    n.vy += (CY - n.y) * CENTER;
  }

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) d2 = 1;
      const force = REPULSION / d2;
      const d = Math.sqrt(d2);
      const fx = (dx / d) * force;
      const fy = (dy / d) * force;
      if (a.fx == null) {
        a.vx += fx;
        a.vy += fy;
      }
      if (b.fx == null) {
        b.vx -= fx;
        b.vy -= fy;
      }
    }
  }

  for (const e of edges) {
    const a = byId.get(e.from);
    const b = byId.get(e.to);
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const d = Math.hypot(dx, dy) || 1;
    const stretch = d - SPRING_LEN;
    const fx = (dx / d) * stretch * SPRING;
    const fy = (dy / d) * stretch * SPRING;
    if (a.fx == null) {
      a.vx += fx;
      a.vy += fy;
    }
    if (b.fx == null) {
      b.vx -= fx;
      b.vy -= fy;
    }
  }

  let ke = 0;
  for (const n of nodes) {
    if (n.fx != null) {
      n.x = n.fx;
      n.y = n.fy!;
      n.vx = 0;
      n.vy = 0;
      continue;
    }
    n.vx *= DAMPING;
    n.vy *= DAMPING;
    n.x += n.vx;
    n.y += n.vy;
    ke += n.vx * n.vx + n.vy * n.vy;
  }
  return ke;
}

const KE_SETTLE_THRESHOLD = 0.02;

export function RingExplorer({ caseAnswer }: { caseAnswer: CaseAnswer }) {
  const reduce = useReducedMotion();
  const ring = useMemo(() => buildRingGraph(caseAnswer), [caseAnswer]);

  const nodesRef = useRef<SimNode[]>(seedPositions(ring.nodes));
  const byIdRef = useRef<Map<string, SimNode>>(
    new Map(nodesRef.current.map((n) => [n.id, n])),
  );
  useEffect(() => {
    nodesRef.current = seedPositions(ring.nodes);
    byIdRef.current = new Map(nodesRef.current.map((n) => [n.id, n]));
  }, [ring.nodes]);

  const [, forceRender] = useState(0);
  const rafRef = useRef<number | null>(null);
  const runningRef = useRef(false);

  const runSim = useCallback(() => {
    if (runningRef.current) return;
    runningRef.current = true;
    const step = () => {
      const ke = tick(nodesRef.current, ring.edges, byIdRef.current);
      forceRender((x) => x + 1);
      if (ke > KE_SETTLE_THRESHOLD) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        runningRef.current = false;
        rafRef.current = null;
      }
    };
    rafRef.current = requestAnimationFrame(step);
  }, [ring.edges]);

  useEffect(() => {
    if (reduce) {
      // Pre-settle synchronously so the layout is meaningful with no rAF loop at all.
      for (let i = 0; i < 300; i++) {
        const ke = tick(nodesRef.current, ring.edges, byIdRef.current);
        if (ke < KE_SETTLE_THRESHOLD) break;
      }
      forceRender((x) => x + 1);
      return;
    }
    runSim();
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      runningRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduce, runSim]);

  // --- interaction state ---
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // pan/zoom
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const panRef = useRef<{ startX: number; startY: number; ox: number; oy: number } | null>(null);

  // replay discovery
  const [revealStage, setRevealStage] = useState(3); // 0..3, 3 = all revealed
  const [replaying, setReplaying] = useState(false);

  const clientToWorld = useCallback(
    (clientX: number, clientY: number) => {
      const svg = svgRef.current;
      if (!svg) return { x: 0, y: 0 };
      const rect = svg.getBoundingClientRect();
      const sx = ((clientX - rect.left) / rect.width) * W;
      const sy = ((clientY - rect.top) / rect.height) * H;
      return { x: (sx - view.x) / view.scale, y: (sy - view.y) / view.scale };
    },
    [view],
  );

  const onNodePointerDown = useCallback(
    (e: React.PointerEvent, id: string) => {
      e.stopPropagation();
      (e.target as Element).setPointerCapture(e.pointerId);
      const n = byIdRef.current.get(id);
      if (!n) return;
      setDraggingId(id);
      const world = clientToWorld(e.clientX, e.clientY);
      n.fx = world.x;
      n.fy = world.y;
      if (!reduce) runSim();
    },
    [clientToWorld, reduce, runSim],
  );

  const onNodePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!draggingId) return;
      const n = byIdRef.current.get(draggingId);
      if (!n) return;
      const world = clientToWorld(e.clientX, e.clientY);
      n.fx = world.x;
      n.fy = world.y;
      if (reduce) {
        n.x = world.x;
        n.y = world.y;
        forceRender((x) => x + 1);
      }
    },
    [draggingId, clientToWorld, reduce],
  );

  const endDrag = useCallback(() => {
    if (draggingId) {
      const n = byIdRef.current.get(draggingId);
      if (n) {
        n.fx = null;
        n.fy = null;
      }
    }
    setDraggingId(null);
  }, [draggingId]);

  // canvas pan (drag empty background)
  const onBgPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (draggingId) return;
      (e.target as Element).setPointerCapture(e.pointerId);
      panRef.current = { startX: e.clientX, startY: e.clientY, ox: view.x, oy: view.y };
    },
    [draggingId, view],
  );
  const onBgPointerMove = useCallback((e: React.PointerEvent) => {
    if (!panRef.current) return;
    const dx = e.clientX - panRef.current.startX;
    const dy = e.clientY - panRef.current.startY;
    setView((v) => ({ ...v, x: panRef.current!.ox + dx, y: panRef.current!.oy + dy }));
  }, []);
  const onBgPointerUp = useCallback(() => {
    panRef.current = null;
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setView((v) => {
      const next = v.scale * (e.deltaY > 0 ? 0.9 : 1.1);
      return { ...v, scale: Math.min(2.5, Math.max(0.5, next)) };
    });
  }, []);

  // hop distance from focused/hovered node's neighbourhood, for dimming.
  const neighborsOf = useCallback(
    (id: string) => {
      const set = new Set<string>([id]);
      for (const e of ring.edges) {
        if (e.from === id) set.add(e.to);
        if (e.to === id) set.add(e.from);
      }
      return set;
    },
    [ring.edges],
  );
  const activeId = hoveredId ?? focusedId;
  const highlighted = activeId ? neighborsOf(activeId) : null;

  const focusedNode = focusedId ? nodesRef.current.find((n) => n.id === focusedId) : null;

  const replayTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => {
    return () => replayTimersRef.current.forEach(clearTimeout);
  }, []);
  const runReplay = useCallback(() => {
    if (reduce) return;
    replayTimersRef.current.forEach(clearTimeout);
    setReplaying(true);
    setRevealStage(0);
    replayTimersRef.current = [
      setTimeout(() => setRevealStage(1), 500),
      setTimeout(() => setRevealStage(2), 1300),
      setTimeout(() => {
        setRevealStage(3);
        setReplaying(false);
        runSim();
      }, 2200),
    ];
  }, [reduce, runSim]);

  const nodes = nodesRef.current;
  const edges = ring.edges;

  const isRevealed = (n: SimNode) => revealStage >= n.hops || n.hops === 0;

  return (
    <figure className="instrument overflow-hidden">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2 border-b border-seam px-4 py-2.5">
        <span className="readout text-[0.68rem] uppercase tracking-[0.14em] text-ink-dim">
          device ring · interactive
        </span>
        <div className="flex items-center gap-3">
          <span className="readout text-[0.68rem] text-ink-faint">
            {ring.nodes.filter((n) => n.kind === "ring-card").length} cards · 1 device
          </span>
          <button
            type="button"
            onClick={runReplay}
            disabled={replaying || Boolean(reduce)}
            className="readout rounded-[var(--r-sm)] border border-seam px-2 py-0.5 text-[0.62rem] uppercase tracking-[0.12em] text-ink-faint transition-colors hover:border-seam-hi hover:text-phosphor disabled:opacity-40"
          >
            replay discovery
          </button>
        </div>
      </figcaption>

      <div className="matrix-bed relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="edge-fade block h-auto w-full touch-none"
          role="img"
          aria-label={`Interactive device ring for case ${caseAnswer.case_id}: the flagged card connects through one shared device to ${
            ring.nodes.filter((n) => n.kind === "ring-card").length
          } other cards. Drag nodes, hover to trace connections, click or press Enter to focus a node.`}
          onPointerDown={onBgPointerDown}
          onPointerMove={(e) => {
            onBgPointerMove(e);
            onNodePointerMove(e);
          }}
          onPointerUp={() => {
            onBgPointerUp();
            endDrag();
          }}
          onPointerCancel={() => {
            onBgPointerUp();
            endDrag();
          }}
          onWheel={onWheel}
        >
          <defs>
            <filter id="ring-halo" x="-70%" y="-70%" width="240%" height="240%">
              <feGaussianBlur stdDeviation="5" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
            {/* Edges curve toward the hub (device) so 17 near-parallel lines bundle
                instead of crosshatching. */}
            <g>
              {edges.map((e, i) => {
                const a = byIdRef.current.get(e.from);
                const b = byIdRef.current.get(e.to);
                if (!a || !b || !isRevealed(a) || !isRevealed(b)) return null;
                const mx = (a.x + b.x) / 2;
                const my = (a.y + b.y) / 2;
                const qx = mx + (CX - mx) * 0.22;
                const qy = my + (CY - my) * 0.22;
                const d = `M ${a.x} ${a.y} Q ${qx} ${qy} ${b.x} ${b.y}`;
                const isHot =
                  highlighted && highlighted.has(e.from) && highlighted.has(e.to);
                return (
                  <path
                    key={`${e.from}-${e.to}-${i}`}
                    d={d}
                    fill="none"
                    stroke={isHot ? "var(--phosphor)" : "var(--hold-lo)"}
                    strokeWidth={isHot ? 1.6 : 1}
                    strokeOpacity={
                      highlighted ? (isHot ? 0.95 : 0.12) : 0.45
                    }
                    style={{ transition: "stroke-opacity 160ms, stroke 160ms" }}
                  />
                );
              })}
            </g>

            <g>
              {nodes.map((n) => {
                if (!isRevealed(n)) return null;
                const dim = highlighted ? !highlighted.has(n.id) : false;
                const isFocused = n.id === focusedId;
                const isHot = n.id === hoveredId;
                const color =
                  n.kind === "device"
                    ? "var(--hold)"
                    : n.kind === "flagged-card"
                      ? "var(--phosphor)"
                      : "var(--seam-hi)";
                const fill =
                  n.kind === "device"
                    ? "oklch(0.268 0.027 255)"
                    : n.kind === "flagged-card"
                      ? "oklch(0.221 0.024 256)"
                      : "oklch(0.181 0.021 257)";

                return (
                  <g
                    key={n.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${n.kind === "device" ? "Shared device" : n.kind === "flagged-card" ? "Flagged card" : "Connected card"} ${n.label}, ${n.hops} hop${n.hops === 1 ? "" : "s"} from the flagged card`}
                    opacity={dim ? 0.22 : 1}
                    style={{
                      transition: reduce
                        ? undefined
                        : "opacity 380ms var(--ease-out-quart)",
                      cursor: "grab",
                      outlineOffset: 4,
                    }}
                    onPointerDown={(e) => onNodePointerDown(e, n.id)}
                    onMouseEnter={() => setHoveredId(n.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    onFocus={() => setHoveredId(n.id)}
                    onBlur={() => setHoveredId((h) => (h === n.id ? null : h))}
                    onClick={() => setFocusedId((f) => (f === n.id ? null : n.id))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setFocusedId((f) => (f === n.id ? null : n.id));
                      }
                    }}
                  >
                    {(n.kind === "device" || n.kind === "flagged-card" || isFocused) && (
                      <circle
                        cx={n.x}
                        cy={n.y}
                        r={n.r + 6}
                        fill="none"
                        stroke={isFocused ? "var(--phosphor)" : color}
                        strokeWidth={1}
                        strokeOpacity={0.45}
                        filter="url(#ring-halo)"
                      />
                    )}
                    <circle
                      cx={n.x}
                      cy={n.y}
                      r={n.r}
                      fill={fill}
                      stroke={isHot || isFocused ? "var(--phosphor)" : color}
                      strokeWidth={isFocused ? 2 : n.kind === "device" ? 1.8 : 1}
                    />
                    {(n.kind === "device" || n.kind === "flagged-card" || isHot || isFocused) && (
                      <text
                        x={n.x}
                        y={n.y + n.r + 13}
                        textAnchor="middle"
                        className="readout"
                        fontSize={n.kind === "device" ? 11 : 10}
                        fill={
                          n.kind === "device"
                            ? "var(--hold)"
                            : n.kind === "flagged-card"
                              ? "var(--phosphor)"
                              : "var(--ink)"
                        }
                      >
                        {n.label.length > 26 ? `${n.label.slice(0, 24)}…` : n.label}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </g>
        </svg>

        {focusedNode && (
          <div className="instrument absolute bottom-3 left-3 max-w-[15rem] p-3">
            <p className="readout text-[0.6rem] uppercase tracking-[0.13em] text-ink-faint">
              focused entity
            </p>
            <p className="mt-1 text-[0.86rem] font-medium text-bright">{focusedNode.label}</p>
            <p className="readout mt-0.5 text-[0.72rem] text-ink-dim">
              kind: {focusedNode.kind === "device" ? "shared device" : focusedNode.kind === "flagged-card" ? "flagged card" : "connected card"}
            </p>
            <p className="readout text-[0.72rem] text-ink-dim">
              {focusedNode.hops} hop{focusedNode.hops === 1 ? "" : "s"} from flagged card
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-seam px-4 py-2.5">
        <Legend color="var(--hold)" label="shared device" />
        <Legend color="var(--phosphor)" label="flagged card" />
        <Legend color="var(--seam-hi)" label="connected card" />
        <span className="readout text-[0.62rem] text-ink-faint">
          drag nodes · scroll to zoom · drag canvas to pan
        </span>
      </div>
    </figure>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span aria-hidden className="h-[7px] w-[7px] rounded-full" style={{ background: color }} />
      <span className="readout text-[0.64rem] uppercase tracking-[0.1em] text-ink-faint">
        {label}
      </span>
    </span>
  );
}
