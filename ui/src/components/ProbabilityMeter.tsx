"use client";

import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { useEffect } from "react";
import { pct2, probabilityBand } from "@/lib/format";

/* The calibrated fraud probability — the number the entire case turns on, and the
   one place in this interface where glow is earned.

   Built as an instrument gauge rather than a progress bar. A progress bar says
   "62% complete"; this has to say "0.84, which is past the line where we stop
   investigating and act." So the policy's own thresholds are etched into the
   track as gradations, and the reading sits above them in the mono face at a
   size that dominates the panel.

   Ticks are the real decision boundaries, not decoration:
     0.15  stop-low  — close as legitimate (README §6)
     0.30  case-creation floor (§3a)
     0.70  R1 block guard — below this, verify before blocking
     0.85  stop-high — close as fraud (§6)

   The value renders to exactly two decimals, never implying more precision than
   the float carries, and is always paired with the band name so the figure is
   never left to be interpreted alone. */

const TICKS: { at: number; label: string }[] = [
  { at: 0.15, label: "0.15" },
  { at: 0.3, label: "0.30" },
  { at: 0.7, label: "0.70" },
  { at: 0.85, label: "0.85" },
];

const TONE: Record<"fraud" | "clear" | "warn", { color: string; glow: string }> = {
  fraud: { color: "var(--fraud)", glow: "glow-fraud" },
  clear: { color: "var(--clear)", glow: "glow-clear" },
  warn: { color: "var(--hold)", glow: "glow-hold" },
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
  const tone = TONE[band.tone];
  const clamped = Math.max(0, Math.min(1, value));

  // Count the reading up rather than snapping it in. A figure that arrives at
  // rest reads as a static label; one that settles reads as a measurement.
  const raw = useMotionValue(reduce ? clamped : 0);
  const text = useTransform(raw, (v) => v.toFixed(2));

  useEffect(() => {
    if (reduce) {
      raw.set(clamped);
      return;
    }
    const controls = animate(raw, clamped, {
      duration: 1.05,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [clamped, raw, reduce]);

  if (size === "compact") {
    return (
      <div className="flex items-center gap-2">
        <div
          className="relative h-1 w-14 overflow-hidden rounded-full bg-ridge"
          role="meter"
          aria-valuenow={Math.round(clamped * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Fraud probability ${pct2(value)}, ${band.label}`}
        >
          <motion.div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{ background: tone.color }}
            initial={{ width: reduce ? `${clamped * 100}%` : 0 }}
            animate={{ width: `${clamped * 100}%` }}
            transition={reduce ? { duration: 0 } : { duration: 0.75, ease: [0.16, 1, 0.3, 1] }}
          />
        </div>
        <span className="readout text-xs text-ink-dim">{pct2(value)}</span>
      </div>
    );
  }

  return (
    <div className="w-full">
      {/* The reading. Mono, large, glowing in the verdict's own colour. */}
      <div className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-2.5">
          <motion.span
            className={`readout text-[3.25rem] leading-none font-medium ${tone.glow}`}
            aria-hidden
          >
            {text}
          </motion.span>
          <span
            className="readout text-[0.7rem] uppercase tracking-[0.14em]"
            style={{ color: tone.color }}
          >
            {band.label}
          </span>
        </div>
        <span className="readout pb-1 text-[0.65rem] uppercase tracking-[0.14em] text-ink-faint">
          fraud probability
        </span>
      </div>

      {/* The track. Gradations are etched into it, so the reading is always
          shown against the thresholds that give it meaning. */}
      <div
        className="relative mt-3 h-[9px] w-full overflow-hidden rounded-[2px] bg-void ring-1 ring-inset ring-seam"
        role="meter"
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Fraud probability ${pct2(value)}, ${band.label}`}
      >
        {/* dark region beyond the stop-high line, so "past the point of acting"
            is visible as territory rather than implied by a number */}
        <div
          className="absolute inset-y-0 right-0"
          style={{ left: "85%", background: "oklch(0.672 0.221 13 / 0.09)" }}
        />
        <motion.div
          className="absolute inset-y-0 left-0"
          style={{
            background: `linear-gradient(90deg, color-mix(in oklch, ${tone.color} 55%, transparent), ${tone.color})`,
            boxShadow: `0 0 16px -2px ${tone.color}`,
          }}
          initial={{ width: reduce ? `${clamped * 100}%` : 0 }}
          animate={{ width: `${clamped * 100}%` }}
          transition={reduce ? { duration: 0 } : { duration: 1.05, ease: [0.16, 1, 0.3, 1] }}
        />
        {TICKS.map((t) => (
          <div
            key={t.at}
            className="absolute inset-y-0 w-px bg-void"
            style={{ left: `${t.at * 100}%` }}
          />
        ))}
      </div>

      {/* Gradation labels. */}
      <div className="relative mt-1.5 h-3">
        {TICKS.map((t) => (
          <span
            key={t.at}
            className="readout absolute -translate-x-1/2 text-[9.5px] text-ink-faint"
            style={{ left: `${t.at * 100}%` }}
          >
            {t.label}
          </span>
        ))}
      </div>
    </div>
  );
}
