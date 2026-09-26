"use client";

import { motion, useReducedMotion } from "motion/react";
import { useRef } from "react";
import type { Verdict, EvidenceSource, ApprovalRoute, CaseStatus } from "@/lib/types";

// Pointer-tracked shine, shared by every badge below: writes the pointer
// position straight to the element's own custom properties on move (no
// setState, so hovering a row full of badges never triggers React) and the
// CSS in globals.css turns that into a highlight that tracks the cursor.
function useBadgeShine<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const onPointerMove = (e: React.PointerEvent<T>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--shine-x", `${((e.clientX - rect.left) / rect.width) * 100}%`);
    el.style.setProperty("--shine-y", `${((e.clientY - rect.top) / rect.height) * 100}%`);
  };
  return { ref, onPointerMove };
}

// Verdict badges are stamped, not pill-shaped: a squared block with a hard inner
// rule, closer to a rubber stamp than a status chip.
const verdictStyle: Record<Verdict, string> = {
  fraud: "bg-fraud/15 text-fraud border-fraud/50",
  legitimate: "bg-clear/15 text-clear border-clear/50",
  uncertain: "bg-hold/15 text-hold border-hold/50",
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const reduce = useReducedMotion();
  const { ref, onPointerMove } = useBadgeShine<HTMLSpanElement>();
  return (
    <motion.span
      key={verdict}
      ref={ref}
      onPointerMove={onPointerMove}
      initial={reduce ? undefined : { opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 16, mass: 0.6 }}
      className={`badge-shine relative inline-flex shrink-0 whitespace-nowrap items-center gap-1.5 overflow-hidden rounded border-2 px-2.5 py-1 font-data text-xs font-medium uppercase tracking-wide ${verdictStyle[verdict]}`}
    >
      <span className="h-1.5 w-1.5 shrink-0 bg-current" aria-hidden />
      <span className="shrink-0 whitespace-nowrap">{verdict}</span>
    </motion.span>
  );
}

const statusLabel: Record<CaseStatus, string> = {
  open: "Open",
  closed_fraud: "Closed — Fraud",
  closed_legitimate: "Closed — Legitimate",
  escalated: "Escalated",
};

export function StatusBadge({ status }: { status: CaseStatus }) {
  return (
    <span className="inline-flex shrink-0 whitespace-nowrap items-center rounded border border-seam-hi bg-deck px-2 py-0.5 font-body text-xs text-ink-dim">
      {statusLabel[status]}
    </span>
  );
}

const sourceLabel: Record<EvidenceSource, string> = {
  graph: "Graph",
  document: "Document",
  customer: "Customer",
  external: "External",
};

const sourceStyle: Record<EvidenceSource, string> = {
  graph: "text-phosphor border-phosphor/40 bg-phosphor/10",
  document: "text-ink-dim border-seam-hi bg-deck",
  customer: "text-hold border-hold/40 bg-hold/10",
  external: "text-clear border-clear/40 bg-clear/10",
};

// A different glyph per source, not just color — so the distinction survives a glance,
// a screenshot, or a color-vision deficiency, not only the palette.
const sourceGlyph: Record<EvidenceSource, string> = {
  graph: "◈", // linked-node diamond
  document: "≡", // stacked lines = document
  customer: "●", // person dot
  external: "↗", // outbound arrow
};

export function SourceBadge({ source }: { source: EvidenceSource }) {
  const { ref, onPointerMove } = useBadgeShine<HTMLSpanElement>();
  return (
    <span
      ref={ref}
      onPointerMove={onPointerMove}
      className={`badge-shine relative inline-flex shrink-0 whitespace-nowrap items-center gap-1 overflow-hidden rounded border px-2 py-0.5 font-data text-[10px] uppercase tracking-wide ${sourceStyle[source]}`}
    >
      <span aria-hidden className="shrink-0">{sourceGlyph[source]}</span>
      <span className="shrink-0 whitespace-nowrap">{sourceLabel[source]}</span>
    </span>
  );
}

const routeStyle: Record<ApprovalRoute, string> = {
  auto: "text-clear border-clear/40 bg-clear/10",
  L1: "text-hold border-hold/40 bg-hold/10",
  L2: "text-fraud border-fraud/40 bg-fraud/10",
};

const routeLabel: Record<ApprovalRoute, string> = {
  auto: "Auto",
  L1: "L1 approval",
  L2: "L2 approval",
};

export function RouteBadge({ route }: { route: ApprovalRoute }) {
  const { ref, onPointerMove } = useBadgeShine<HTMLSpanElement>();
  return (
    <span
      ref={ref}
      onPointerMove={onPointerMove}
      className={`badge-shine relative inline-flex shrink-0 whitespace-nowrap items-center overflow-hidden rounded border px-1.5 py-0.5 font-data text-[10px] uppercase tracking-wide ${routeStyle[route]}`}
    >
      <span className="shrink-0 whitespace-nowrap">{routeLabel[route]}</span>
    </span>
  );
}
