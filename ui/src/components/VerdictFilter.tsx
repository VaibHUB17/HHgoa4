"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import type { CaseAnswer, Verdict } from "@/lib/types";
import { CaseListRow } from "./CaseListRow";

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
            className={`relative rounded-full border px-3 py-1.5 font-body text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-signal ${
              filter === f.value
                ? "border-signal/50 text-signal"
                : "border-line-hi bg-panel text-dim hover:text-paper"
            }`}
          >
            {filter === f.value && (
              <motion.span
                layoutId="verdict-filter-active"
                className="absolute inset-0 rounded-full bg-signal/15"
                transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 400, damping: 32 }}
              />
            )}
            <span className="relative">
              {f.label}
              <span className="ml-1.5 font-data text-[10px] text-faint">{counts[f.value] ?? 0}</span>
            </span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-[110px_1fr_170px_120px_140px] gap-4 px-4 pb-2 font-data text-[10px] uppercase tracking-wide text-faint">
        <span>Case</span>
        <span>Pattern</span>
        <span>Fraud probability</span>
        <span>Exposure</span>
        <span>Verdict / status</span>
      </div>

      <motion.div layout className="space-y-1.5">
        <AnimatePresence initial={false}>
          {filtered.map((c) => (
            <CaseListRow key={c.case_id} c={c} />
          ))}
        </AnimatePresence>
        {filtered.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-faint">No cases match this filter.</p>
        )}
      </motion.div>
    </div>
  );
}
