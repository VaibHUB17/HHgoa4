"use client";

import { useMemo } from "react";
import { motion, useReducedMotion } from "motion/react";
import type { CaseGraph, GraphNode, GraphNodeKind } from "@/lib/types";

// Hand-authored inline SVG, deterministic radial layout — no d3, no physics sim. Nodes are
// grouped by kind into concentric rings (Customer/Card at center, Transaction and
// DeviceProfile/BillingRegion further out) so the layout is stable and reproducible for the
// same case every render. Shared DeviceProfile nodes are the ring-detection story: any device
// with more than one edge into it is drawn larger, in the signal-teal accent, with a visible
// halo, so a shared device across cards reads as obviously different from a single-card node.

const KIND_ORDER: GraphNodeKind[] = ["Customer", "Card", "Transaction", "DeviceProfile", "BillingRegion"];

const KIND_COLOR: Record<GraphNodeKind, string> = {
  Customer: "#e7ebf0",
  Card: "#4f8ff0",
  Transaction: "#8d99ab",
  DeviceProfile: "#2dd4bf",
  BillingRegion: "#e8a53d",
};

const W = 640;
const H = 440;
const CX = W / 2;
const CY = H / 2;

interface Positioned extends GraphNode {
  x: number;
  y: number;
  degree: number;
}

function layout(graph: CaseGraph): Positioned[] {
  const degree = new Map<string, number>();
  for (const e of graph.edges) {
    degree.set(e.from, (degree.get(e.from) ?? 0) + 1);
    degree.set(e.to, (degree.get(e.to) ?? 0) + 1);
  }

  const byKind = new Map<GraphNodeKind, GraphNode[]>();
  for (const kind of KIND_ORDER) byKind.set(kind, []);
  for (const n of graph.nodes) byKind.get(n.kind)?.push(n);

  const ringRadius: Record<GraphNodeKind, number> = {
    Customer: 40,
    Card: 120,
    Transaction: 200,
    DeviceProfile: 200,
    BillingRegion: 200,
  };

  const positioned: Positioned[] = [];
  // Outer ring kinds (Transaction/DeviceProfile/BillingRegion) share the same radius but
  // occupy distinct angular sectors so they don't overlap.
  const outerKinds: GraphNodeKind[] = ["Transaction", "DeviceProfile", "BillingRegion"];
  const sectorSpan = (2 * Math.PI) / outerKinds.length;

  for (const kind of KIND_ORDER) {
    const nodes = byKind.get(kind) ?? [];
    const r = ringRadius[kind];
    if (kind === "Customer" || kind === "Card") {
      nodes.forEach((n, i) => {
        const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2;
        positioned.push({
          ...n,
          x: CX + r * Math.cos(angle),
          y: CY + r * Math.sin(angle),
          degree: degree.get(n.id) ?? 0,
        });
      });
    } else {
      const sectorIndex = outerKinds.indexOf(kind);
      const start = sectorIndex * sectorSpan;
      nodes.forEach((n, i) => {
        const angle = start + (sectorSpan * (i + 0.5)) / Math.max(nodes.length, 1) - Math.PI / 2;
        positioned.push({
          ...n,
          x: CX + r * Math.cos(angle),
          y: CY + r * Math.sin(angle),
          degree: degree.get(n.id) ?? 0,
        });
      });
    }
  }

  return positioned;
}

export function CaseGraphView({ graph }: { graph: CaseGraph }) {
  const reduce = useReducedMotion();
  const nodes = useMemo(() => layout(graph), [graph]);
  const posById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  return (
    <div className="rounded-xl border border-line-hi bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-data text-xs uppercase tracking-wide text-faint">
          Entity neighborhood
        </h3>
        <div className="flex items-center gap-3 text-[10px] font-data text-faint">
          {KIND_ORDER.map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: KIND_COLOR[k] }}
              />
              {k}
            </span>
          ))}
        </div>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="Entity neighborhood graph showing customers, cards, transactions, and shared device profiles"
      >
        <g>
          {graph.edges.map((e, i) => {
            const from = posById.get(e.from);
            const to = posById.get(e.to);
            if (!from || !to) return null;
            const sharedDevice = to.kind === "DeviceProfile" && to.degree > 2;
            return (
              <motion.line
                key={`${e.from}-${e.to}-${i}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke={sharedDevice ? "#2dd4bf" : "#2a3341"}
                strokeWidth={sharedDevice ? 1.75 : 1}
                strokeOpacity={sharedDevice ? 0.8 : 0.6}
                initial={reduce ? undefined : { pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: sharedDevice ? 0.8 : 0.6 }}
                transition={reduce ? { duration: 0 } : { duration: 0.5, delay: i * 0.03 }}
              />
            );
          })}
        </g>
        <g>
          {nodes.map((n, i) => {
            const isSharedDevice = n.kind === "DeviceProfile" && n.degree > 2;
            const radius = n.kind === "Customer" ? 16 : isSharedDevice ? 14 : n.kind === "Card" ? 12 : 8;
            return (
              <motion.g
                key={n.id}
                initial={reduce ? undefined : { opacity: 0, scale: 0.6 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={
                  reduce
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 220, damping: 18, delay: i * 0.025 }
                }
              >
                {isSharedDevice && (
                  <circle
                    cx={n.x}
                    cy={n.y}
                    r={radius + 8}
                    fill="none"
                    stroke="#2dd4bf"
                    strokeWidth={1.5}
                    strokeDasharray="3 3"
                    opacity={0.6}
                  />
                )}
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={radius}
                  fill={n.kind === "Card" || n.kind === "Transaction" ? "#171e28" : KIND_COLOR[n.kind]}
                  stroke={n.fraud ? "#f2578a" : KIND_COLOR[n.kind]}
                  strokeWidth={n.flagged || n.fraud ? 2.5 : 1.5}
                />
                <text
                  x={n.x}
                  y={n.y + radius + 14}
                  textAnchor="middle"
                  fontSize={9}
                  fontFamily="var(--font-data)"
                  fill={isSharedDevice ? "#2dd4bf" : "#8d99ab"}
                >
                  {n.label.length > 22 ? `${n.label.slice(0, 20)}…` : n.label}
                </text>
              </motion.g>
            );
          })}
        </g>
      </svg>
      {nodes.some((n) => n.kind === "DeviceProfile" && n.degree > 2) && (
        <p className="mt-2 text-xs text-signal">
          Dashed halo marks a device profile shared across multiple cards — the ring signal
          behind R6.
        </p>
      )}
    </div>
  );
}
