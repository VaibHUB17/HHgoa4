"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { useRef } from "react";
import type { CaseAnswer } from "@/lib/types";
import { usd } from "@/lib/format";
import { VerdictBadge, StatusBadge } from "./Badges";
import { ProbabilityMeter } from "./ProbabilityMeter";

const verdictColor: Record<CaseAnswer["case"]["verdict"], string> = {
  fraud: "var(--fraud)",
  legitimate: "var(--clear)",
  uncertain: "var(--hold)",
};

// Stagger by list index reads as intentional for the first screenful and would
// read as a stall by row 40 — cap how much of the index actually delays entry
// rather than letting it grow unbounded.
const STAGGER_STEP = 0.028;
const STAGGER_CAP = 0.42;

export function CaseListRow({ c, index = 0 }: { c: CaseAnswer; index?: number }) {
  const reduce = useReducedMotion();
  const linkRef = useRef<HTMLAnchorElement>(null);
  const delay = Math.min(index * STAGGER_STEP, STAGGER_CAP);

  // Cursor-tracked highlight: written straight to the element's style on every
  // pointermove, no setState — a radial glow that follows the pointer without
  // triggering React at 60fps.
  const handlePointerMove = (e: React.PointerEvent<HTMLAnchorElement>) => {
    const el = linkRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--spot-x", `${e.clientX - rect.left}px`);
    el.style.setProperty("--spot-y", `${e.clientY - rect.top}px`);
  };

  return (
    <motion.div
      layout
      initial={reduce ? undefined : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? undefined : { opacity: 0, y: -6 }}
      transition={
        reduce
          ? { duration: 0 }
          : { type: "spring", stiffness: 340, damping: 30, delay }
      }
      className="group"
    >
      <Link
        ref={linkRef}
        href={`/cases/${c.case_id}`}
        onPointerMove={handlePointerMove}
        style={{ "--spot-x": "50%", "--spot-y": "50%" } as React.CSSProperties}
        className="row-spotlight relative grid grid-cols-[3px_110px_1fr_170px_120px_140px] items-center gap-4 overflow-hidden border border-transparent py-3 pr-4 pl-0 transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:border-seam hover:bg-ridge focus-visible:outline-2 focus-visible:outline-phosphor"
      >
        {/* Left-edge verdict indicator: a hairline at rest that grows into a
            full-height bar on hover/focus, drawn from the case's own verdict
            colour rather than a generic accent stripe. */}
        <span
          aria-hidden
          className="row-edge h-2 w-[3px] justify-self-center rounded-full transition-[height] duration-200 ease-[cubic-bezier(0.25,1,0.5,1)] group-hover:h-8 group-focus-visible:h-8"
          style={{ background: verdictColor[c.case.verdict] }}
        />

        <span className="readout pl-4 text-sm text-bright">{c.case_id}</span>

        <div className="min-w-0">
          <p className="truncate text-sm text-ink">
            {c.case.pattern === "none" ? "No pattern" : c.case.pattern.replace(/_/g, " ")}
          </p>
          <p className="mt-0.5 truncate text-xs text-ink-faint">{c.case.summary}</p>
        </div>

        <div className="w-full">
          <ProbabilityMeter value={c.case.fraud_probability} size="compact" />
        </div>

        <span className="readout text-sm text-bright">{usd(c.case.exposure_usd)}</span>

        <div className="flex flex-col items-start gap-1.5">
          <VerdictBadge verdict={c.case.verdict} />
          <StatusBadge status={c.case.status} />
        </div>
      </Link>
    </motion.div>
  );
}
