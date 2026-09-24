"use client";

import { useEffect, useState, useMemo } from "react";
import {
  motion,
  AnimatePresence,
  animate,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "motion/react";
import type { CaseAnswer, Verdict } from "@/lib/types";
import { CaseListRow } from "./CaseListRow";

// A tab's own count ticks up/down rather than jumping to the new digit — the
// same count-up idiom ProbabilityMeter uses for its reading, reused here so a
// filter change reads as a recount rather than a re-render.
function TickingCount({ value }: { value: number }) {
  const reduce = useReducedMotion();
  const raw = useMotionValue(value);
  const text = useTransform(raw, (v) => Math.round(v).toString());

  useEffect(() => {
    if (reduce) {
      raw.set(value);
      return;
    }
    const controls = animate(raw, value, { duration: 0.32, ease: [0.16, 1, 0.3, 1] });
    return () => controls.stop();
  }, [value, raw, reduce]);

  return <motion.span className="ml-1.5 readout text-[10px] text-ink-faint">{text}</motion.span>;
}

const FILTERS: { value: Verdict | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "fraud", label: "Fraud" },
  { value: "uncertain", label: "Uncertain" },
  { value: "legitimate", label: "Legitimate" },
];

export function VerdictFilter({ cases }: { cases: CaseAnswer[] }) {
  const [filter, setFilter] = useState<Verdict | "all">("all");
  const reduce = useReducedMotion();

  const filtered = useMemo(
    () => (filter === "all" ? cases : cases.filter((c) => c.case.verdict === filter)),
    [cases, filter]
  );

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: cases.length, fraud: 0, uncertain: 0, legitimate: 0 };
    for (const c of cases) m[c.case.verdict] = (m[c.case.verdict] ?? 0) + 1;
    return m;
  }, [cases]);

  return (
    <div>
      <div role="tablist" aria-label="Filter by verdict" className="mb-4 flex gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            role="tab"
            aria-selected={filter === f.value}
            onClick={() => setFilter(f.value)}
            className={`relative rounded-full border px-3 py-1.5 font-body text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-phosphor ${
              filter === f.value
                ? "border-phosphor/50 text-phosphor"
                : "border-seam-hi bg-bed text-ink-dim hover:text-bright"
            }`}
          >
            {filter === f.value && (
              <motion.span
                layoutId="verdict-filter-active"
                className="absolute inset-0 rounded-full bg-phosphor/15"
                transition={
                  reduce
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 500, damping: 22, mass: 0.7 }
                }
              />
            )}
            <span className="relative">
              {f.label}
              <TickingCount value={counts[f.value] ?? 0} />
            </span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-[110px_1fr_170px_120px_140px] gap-4 px-4 pb-2 readout text-[10px] uppercase tracking-wide text-ink-faint">
        <span>Case</span>
        <span>Pattern</span>
        <span>Fraud probability</span>
        <span>Exposure</span>
        <span>Verdict / status</span>
      </div>

      <motion.div layout className="space-y-1.5">
        <AnimatePresence initial={false}>
          {filtered.map((c, i) => (
            <CaseListRow key={c.case_id} c={c} index={i} />
          ))}
        </AnimatePresence>
        {filtered.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-ink-faint">No cases match this filter.</p>
        )}
      </motion.div>
    </div>
  );
}
