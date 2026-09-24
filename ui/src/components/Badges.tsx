"use client";

import { motion, useReducedMotion } from "motion/react";
import type { Verdict, EvidenceSource, ApprovalRoute, CaseStatus } from "@/lib/types";

// Verdict badges are stamped, not pill-shaped: a squared block with a hard inner
// rule, closer to a rubber stamp than a status chip.
const verdictStyle: Record<Verdict, string> = {
  fraud: "bg-fraud/15 text-fraud border-fraud/50",
  legitimate: "bg-clear/15 text-clear border-clear/50",
  uncertain: "bg-hold/15 text-hold border-hold/50",
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const reduce = useReducedMotion();
  return (
    <motion.span
      key={verdict}
      initial={reduce ? undefined : { opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 320, damping: 20 }}
      className={`inline-flex items-center gap-1.5 rounded border-2 px-2.5 py-1 font-data text-xs font-medium uppercase tracking-wide ${verdictStyle[verdict]}`}
    >
      <span className="h-1.5 w-1.5 bg-current" aria-hidden />
      {verdict}
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
    <span className="inline-flex items-center rounded border border-seam-hi bg-deck px-2 py-0.5 font-body text-xs text-ink-dim">
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
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-data text-[10px] uppercase tracking-wide ${sourceStyle[source]}`}
    >
      <span aria-hidden>{sourceGlyph[source]}</span>
      {sourceLabel[source]}
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
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 font-data text-[10px] uppercase tracking-wide ${routeStyle[route]}`}
    >
      {routeLabel[route]}
    </span>
  );
}
