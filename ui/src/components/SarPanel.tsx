"use client";

import { motion, useReducedMotion } from "motion/react";
import type { SarRecord } from "@/lib/types";
import { usd } from "@/lib/format";

// A SAR is a real regulatory filing, not another card in the record — the entrance should
// read like a document being stamped, not a panel fading up. The seal rotates in slightly
// past its resting angle and settles, like ink hitting paper; the panel itself arrives with
// a firm, deliberate spring rather than the quick snaps used for approve/reject controls.
export function SarPanel({ sar }: { sar: SarRecord }) {
  const reduce = useReducedMotion();
  if (!sar.file) return null;

  return (
    <motion.div
      initial={reduce ? undefined : { opacity: 0, y: 14, scale: 0.98 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 160, damping: 22 }}
      className="instrument relative overflow-hidden border-seam-hi p-5"
    >
      <div className="mb-3 flex items-center justify-between border-b border-seam pb-3">
        <div>
          <p className="readout text-[10px] uppercase tracking-widest text-ink-faint">
            Regulatory filing
          </p>
          <h3 className="mt-0.5 font-display text-lg text-bright">Suspicious Activity Report</h3>
        </div>
        <motion.span
          initial={reduce ? undefined : { opacity: 0, scale: 1.6, rotate: -14 }}
          whileInView={{ opacity: 1, scale: 1, rotate: -8 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={
            reduce
              ? { duration: 0 }
              : { type: "spring", stiffness: 220, damping: 14, delay: 0.15 }
          }
          className="rounded border-2 border-fraud/60 bg-fraud/10 px-2 py-0.5 readout text-[10px] uppercase tracking-wide text-fraud"
        >
          Filing required
        </motion.span>
      </div>
      <p className="mb-4 text-xs text-ink-dim">{sar.reason}</p>
      <p className="mb-4 whitespace-pre-wrap text-sm leading-relaxed text-ink">
        {sar.narrative}
      </p>
      <div className="grid grid-cols-2 gap-4 border-t border-seam pt-3 sm:grid-cols-4">
        <div>
          <p className="readout text-[10px] uppercase tracking-wide text-ink-faint">Amount</p>
          <p className="readout text-sm text-bright">{usd(sar.total_amount_usd)}</p>
        </div>
        <div>
          <p className="readout text-[10px] uppercase tracking-wide text-ink-faint">Activity dates</p>
          <p className="readout text-sm text-bright">
            {sar.activity_dates.length === 2 ? `${sar.activity_dates[0]} to ${sar.activity_dates[1]}` : "—"}
          </p>
        </div>
        <div className="col-span-2 sm:col-span-2">
          <p className="readout text-[10px] uppercase tracking-wide text-ink-faint">Subjects</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {sar.subjects.map((s) => (
              <span key={s} className="rounded border border-seam bg-deck px-1.5 py-0.5 readout text-xs text-ink-dim">
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
