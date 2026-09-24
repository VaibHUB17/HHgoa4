"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import type { CaseAnswer } from "@/lib/types";
import { usd } from "@/lib/format";
import { VerdictBadge, StatusBadge } from "./Badges";
import { ProbabilityMeter } from "./ProbabilityMeter";

export function CaseListRow({ c }: { c: CaseAnswer }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      layout
      initial={reduce ? undefined : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? undefined : { opacity: 0, y: -8 }}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 300, damping: 28 }}
      whileHover={reduce ? undefined : { y: -2 }}
      className="group"
    >
      <Link
        href={`/cases/${c.case_id}`}
        className="grid grid-cols-[110px_1fr_170px_120px_140px] items-center gap-4 rounded-lg border border-line bg-panel/0 px-4 py-3 shadow-[0_0_0_0_rgba(0,0,0,0)] transition-[background-color,border-color,box-shadow] duration-200 hover:border-line-hi hover:bg-panel hover:shadow-[0_8px_20px_-8px_rgba(0,0,0,0.5)] focus-visible:outline-2 focus-visible:outline-signal"
      >
        <span className="font-data text-sm text-paper">{c.case_id}</span>

        <div className="min-w-0">
          <p className="truncate text-sm text-paper">
            {c.case.pattern === "none" ? "No pattern" : c.case.pattern.replace(/_/g, " ")}
          </p>
          <p className="mt-0.5 truncate text-xs text-faint">{c.case.summary}</p>
        </div>

        <div className="w-full">
          <ProbabilityMeter value={c.case.fraud_probability} size="compact" />
        </div>

        <span className="font-data text-sm text-paper">{usd(c.case.exposure_usd)}</span>

        <div className="flex flex-col items-start gap-1.5">
          <VerdictBadge verdict={c.case.verdict} />
          <StatusBadge status={c.case.status} />
        </div>
      </Link>
    </motion.div>
  );
}
