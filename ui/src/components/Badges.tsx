"use client";

import { motion, useReducedMotion } from "motion/react";
import type { Verdict, EvidenceSource, ApprovalRoute, CaseStatus } from "@/lib/types";

const verdictStyle: Record<Verdict, string> = {
  fraud: "bg-fraud/15 text-fraud border-fraud/40",
  legitimate: "bg-clear/15 text-clear border-clear/40",
  uncertain: "bg-warn/15 text-warn border-warn/40",
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const reduce = useReducedMotion();
  return (
    <motion.span
      key={verdict}
      initial={reduce ? undefined : { opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 320, damping: 20 }}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-data text-xs uppercase tracking-wide ${verdictStyle[verdict]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
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
    <span className="inline-flex items-center rounded border border-line-hi bg-panel-hi px-2 py-0.5 font-body text-xs text-dim">
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
  graph: "text-signal border-signal/40 bg-signal/10",
  document: "text-dim border-line-hi bg-panel-hi",
  customer: "text-warn border-warn/40 bg-warn/10",
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
  L1: "text-warn border-warn/40 bg-warn/10",
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
