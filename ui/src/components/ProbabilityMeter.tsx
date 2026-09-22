"use client";

import { motion, useReducedMotion } from "motion/react";
import { pct2, probabilityBand } from "@/lib/format";

// The calibrated probability bar. Ticks sit at the policy's own thresholds (RESEARCH.md
// §7.2 / README §6 stopping rule): .15 and .85 (stop-low / stop-high), .30 (case-creation
// floor), .70 (R1 block guard). Value always renders to exactly 2 decimals — never implying
// more precision than the float carries — and is paired with a text band, never a bare number.

const TICKS = [0.15, 0.3, 0.7, 0.85];

const toneColor: Record<"fraud" | "clear" | "warn", string> = {
  fraud: "var(--fraud)",
  clear: "var(--clear)",
  warn: "var(--warn)",
};

export function ProbabilityMeter({
  value,
  size = "full",
}: {
  value: number;
  size?: "full" | "compact";
}) {
  const reduce = useReducedMotion();
  const band = probabilityBand(value);
  const pct = Math.max(0, Math.min(1, value)) * 100;

  return (
    <div className="w-full">
      <div className="flex items-baseline justify-between mb-1.5">
        <span
          className="font-data text-xs uppercase tracking-wide"
          style={{ color: toneColor[band.tone] }}
        >
          {band.label}
        </span>
        <span className="font-data text-sm text-paper tabular-nums">{pct2(value)}</span>
      </div>
      <div
        className="relative w-full rounded-full bg-panel-hi overflow-hidden"
        style={{ height: size === "full" ? 10 : 6 }}
        role="meter"
        aria-valuenow={Math.round(value * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Fraud probability ${pct2(value)}, ${band.label}`}
      >
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: toneColor[band.tone] }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 120, damping: 20 }}
        />
        {size === "full" &&
          TICKS.map((t) => (
            <div
              key={t}
              className="absolute inset-y-0 w-px bg-slate/60"
              style={{ left: `${t * 100}%` }}
            />
          ))}
      </div>
      {size === "full" && (
        <div className="relative mt-1 h-3 text-[10px] font-data text-faint">
          {TICKS.map((t) => (
            <span
              key={t}
              className="absolute -translate-x-1/2"
              style={{ left: `${t * 100}%` }}
            >
              {t.toFixed(2)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
