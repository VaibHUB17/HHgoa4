"use client";

import { motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import type { CaseGraph, GraphNode } from "@/lib/types";

/* The entity neighbourhood — the argument for why this is a graph problem at all.
   A per-transaction model scoring one payment cannot see the other seventeen cards
   on the same handset. Two hops can, and on HHG-014 that is the whole case.

   Layout is deliberate, not a physics simulation. When one device is shared across
   many customers' cards, the truthful picture is radial: the shared element at the
   centre, everything that touches it arranged around it. A force layout would spend
   frames converging on roughly that shape while jittering, and would produce a
   different picture on every load. Deterministic beats organic here — an analyst
   should be able to revisit a case and recognise it.

   Signal encoding, one channel each so they never compete:
     halo + saturation  -> flagged / fraud
     opacity            -> distance from the focal card
     stroke weight      -> primary path vs peripheral
*/

type Placed = GraphNode & { x: number; y: number; r: number; ring: number };

const W = 760;
const H = 440;
const CX = W / 2;
const CY = H / 2;

const KIND_STYLE: Record<
  GraphNode["kind"],
  { fill: string; stroke: string; r: number }
> = {
  DeviceProfile: { fill: "oklch(0.268 0.027 255)", stroke: "var(--hold)", r: 26 },
  Card: { fill: "oklch(0.221 0.024 256)", stroke: "var(--seam-hi)", r: 13 },
  Customer: { fill: "oklch(0.181 0.021 257)", stroke: "var(--seam)", r: 9 },
  Transaction: { fill: "oklch(0.221 0.024 256)", stroke: "var(--phosphor-lo)", r: 8 },
  BillingRegion: { fill: "oklch(0.221 0.024 256)", stroke: "var(--seam)", r: 10 },
};

function layout(graph: CaseGraph, primaryCardId: string): Placed[] {
  const devices = graph.nodes.filter((n) => n.kind === "DeviceProfile");
  const hub = devices[0];

  const placed: Placed[] = [];
  const seen = new Set<string>();

  const put = (n: GraphNode, x: number, y: number, ring: number) => {
    if (seen.has(n.id)) return;
    seen.add(n.id);
    placed.push({ ...n, x, y, r: KIND_STYLE[n.kind].r, ring });
  };

  // The shared device takes the centre when there is one — it is the thing the
  // case is actually about.
  if (hub) put(hub, CX, CY, 0);

  // Cards orbit the hub. The card under investigation is pinned left of centre so
  // the eye has a fixed anchor across cases.
  const cards = graph.nodes.filter((n) => n.kind === "Card");
  const others = cards.filter((c) => c.id !== primaryCardId);
  const primary = cards.find((c) => c.id === primaryCardId);

  if (primary) put(primary, CX - 250, CY, 1);

  const rx = 232;
  const ry = 150;
  others.forEach((c, i) => {
    // Sweep the arc to the right of the hub, leaving the left clear for the
    // primary card and its transactions.
    const t = others.length === 1 ? 0.5 : i / (others.length - 1);
    const angle = -Math.PI * 0.62 + t * Math.PI * 1.24;
    put(c, CX + Math.cos(angle) * rx, CY + Math.sin(angle) * ry, 1);
  });

  // Transactions hang off the primary card.
  const txns = graph.nodes.filter((n) => n.kind === "Transaction");
  txns.forEach((t, i) => {
    const spread = (i - (txns.length - 1) / 2) * 42;
    put(t, CX - 340, CY + spread, 2);
  });

  // Customers sit just outside their card, small and dim — they are context.
  const customers = graph.nodes.filter((n) => n.kind === "Customer");
  customers.forEach((cu) => {
    const ownedCard = placed.find(
      (p) => p.kind === "Card" && p.id.startsWith(cu.id),
    );
    if (ownedCard) {
      const dx = ownedCard.x - CX;
      const dy = ownedCard.y - CY;
      const len = Math.hypot(dx, dy) || 1;
      put(cu, ownedCard.x + (dx / len) * 34, ownedCard.y + (dy / len) * 34, 2);
    }
  });

  // Anything unplaced (defensive) goes on an outer ring.
  graph.nodes.forEach((n, i) => {
    if (!seen.has(n.id)) {
      const a = (i / graph.nodes.length) * Math.PI * 2;
      put(n, CX + Math.cos(a) * 320, CY + Math.sin(a) * 190, 3);
    }
  });

  return placed;
}

export function CaseGraphView({
  graph,
  primaryCardId,
}: {
  graph: CaseGraph;
  primaryCardId: string;
}) {
  const reduce = useReducedMotion();
  const [hovered, setHovered] = useState<string | null>(null);

  const placed = useMemo(() => layout(graph, primaryCardId), [graph, primaryCardId]);
  const byId = useMemo(
    () => new Map(placed.map((p) => [p.id, p])),
    [placed],
  );

  const deviceCount = placed.filter((p) => p.kind === "DeviceProfile").length;
  const cardCount = placed.filter((p) => p.kind === "Card").length;

  return (
    <figure className="instrument overflow-hidden">
      <figcaption className="flex items-baseline justify-between border-b border-seam px-4 py-2.5">
        <span className="readout text-[0.68rem] uppercase tracking-[0.14em] text-ink-dim">
          entity neighbourhood
        </span>
        <span className="readout text-[0.68rem] text-ink-faint">
          {cardCount} cards · {deviceCount} device{deviceCount === 1 ? "" : "s"}
        </span>
      </figcaption>

      <div className="matrix-bed">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="edge-fade block h-auto w-full"
          role="img"
          aria-label={`Entity graph for ${primaryCardId}: ${cardCount} cards connected through ${deviceCount} shared device profile${deviceCount === 1 ? "" : "s"}.`}
        >
          <defs>
            <filter id="node-halo" x="-70%" y="-70%" width="240%" height="240%">
              <feGaussianBlur stdDeviation="5" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Edges first, beneath the nodes. Each traces in, so the relationships
              are seen being discovered rather than presented pre-formed. */}
          <g>
            {graph.edges.map((e, i) => {
              const a = byId.get(e.from);
              const b = byId.get(e.to);
              if (!a || !b) return null;

              const isDevice = a.kind === "DeviceProfile" || b.kind === "DeviceProfile";
              const touchesPrimary = e.from === primaryCardId || e.to === primaryCardId;
              const isHot = hovered === e.from || hovered === e.to;

              // Curve every edge slightly toward the hub. Near-parallel edges then
              // read as a bundle instead of a crosshatch, which is what keeps a
              // seventeen-card ring legible instead of a hairball.
              const mx = (a.x + b.x) / 2;
              const my = (a.y + b.y) / 2;
              const qx = mx + (CX - mx) * 0.22;
              const qy = my + (CY - my) * 0.22;
              const d = `M ${a.x} ${a.y} Q ${qx} ${qy} ${b.x} ${b.y}`;
              const len = Math.hypot(b.x - a.x, b.y - a.y) * 1.25;

              return (
                <motion.path
                  key={`${e.from}-${e.to}-${i}`}
                  d={d}
                  fill="none"
                  stroke={
                    isHot
                      ? "var(--phosphor)"
                      : isDevice
                        ? "var(--hold-lo)"
                        : "var(--seam-hi)"
                  }
                  strokeWidth={touchesPrimary || isHot ? 1.5 : 1}
                  strokeOpacity={isHot ? 0.95 : isDevice ? 0.55 : 0.35}
                  style={{ transition: "stroke 160ms, stroke-opacity 160ms" }}
                  initial={reduce ? false : { strokeDasharray: len, strokeDashoffset: len }}
                  animate={reduce ? undefined : { strokeDashoffset: 0 }}
                  transition={{
                    duration: 0.85,
                    delay: 0.15 + Math.min(i, 24) * 0.022,
                    ease: [0.16, 1, 0.3, 1],
                  }}
                />
              );
            })}
          </g>

          {/* Nodes */}
          <g>
            {placed.map((n, i) => {
              const style = KIND_STYLE[n.kind];
              const isPrimary = n.id === primaryCardId;
              const flagged = Boolean(n.fraud || n.flagged);
              const isHub = n.kind === "DeviceProfile";
              const isHot = hovered === n.id;

              // Depth cue: the further from the focal card, the quieter.
              const depthOpacity = n.ring === 0 ? 1 : n.ring === 1 ? 0.94 : 0.62;

              return (
                <motion.g
                  key={n.id}
                  opacity={depthOpacity}
                  initial={reduce ? false : { opacity: 0, scale: 0.6 }}
                  animate={reduce ? undefined : { opacity: depthOpacity, scale: 1 }}
                  transition={{
                    type: "spring",
                    stiffness: 260,
                    damping: 24,
                    delay: 0.1 + Math.min(i, 26) * 0.024,
                  }}
                  onMouseEnter={() => setHovered(n.id)}
                  onMouseLeave={() => setHovered(null)}
                  style={{ cursor: "default" }}
                >
                  {/* Halo strictly as alarm: the hub and anything flagged. Applying
                      it to every node would dilute the one channel that means
                      "look here." */}
                  {(isHub || flagged || isPrimary) && (
                    <circle
                      cx={n.x}
                      cy={n.y}
                      r={style.r + 5}
                      fill="none"
                      stroke={isHub ? "var(--hold)" : flagged ? "var(--fraud)" : "var(--phosphor)"}
                      strokeWidth={1}
                      strokeOpacity={0.4}
                      filter="url(#node-halo)"
                    >
                      {!reduce && (
                        <animate
                          attributeName="stroke-opacity"
                          values="0.18;0.5;0.18"
                          dur="3.2s"
                          repeatCount="indefinite"
                        />
                      )}
                    </circle>
                  )}

                  <circle
                    cx={n.x}
                    cy={n.y}
                    r={style.r}
                    fill={style.fill}
                    stroke={
                      isHot
                        ? "var(--phosphor)"
                        : flagged
                          ? "var(--fraud)"
                          : isPrimary
                            ? "var(--phosphor)"
                            : style.stroke
                    }
                    strokeWidth={isPrimary || isHub || flagged ? 1.8 : 1}
                    style={{ transition: "stroke 160ms" }}
                  />

                  {/* Label only where it earns the space: the hub, the focal card,
                      and whatever is hovered. Labelling all twenty is a hairball. */}
                  {(isHub || isPrimary || isHot) && (
                    <text
                      x={n.x}
                      y={n.y + style.r + 14}
                      textAnchor="middle"
                      className="readout"
                      fontSize={isHub ? 11 : 10}
                      fill={isHub ? "var(--hold)" : isPrimary ? "var(--phosphor)" : "var(--ink)"}
                    >
                      {n.label.length > 26 ? `${n.label.slice(0, 24)}…` : n.label}
                    </text>
                  )}
                </motion.g>
              );
            })}
          </g>
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-seam px-4 py-2.5">
        <Legend color="var(--hold)" label="shared device" />
        <Legend color="var(--phosphor)" label="card under investigation" />
        <Legend color="var(--fraud)" label="flagged" />
        <Legend color="var(--seam-hi)" label="connected card" />
      </div>
    </figure>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        aria-hidden
        className="h-[7px] w-[7px] rounded-full"
        style={{ background: color }}
      />
      <span className="readout text-[0.64rem] uppercase tracking-[0.1em] text-ink-faint">
        {label}
      </span>
    </span>
  );
}
