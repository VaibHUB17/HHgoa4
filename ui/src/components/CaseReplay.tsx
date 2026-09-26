"use client";

// Scrubbable investigation replay. Drag the timeline, watch the probability,
// evidence, and recommendation recompute at each step from the case's own
// JSON — nothing here is a canned animation. See src/lib/replayData.ts for
// how each step's probability and recommendation are derived from the real
// evidence_weights.yaml formula.

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { pct2, probabilityBand } from "@/lib/format";
import { buildReplaySequence } from "@/lib/replayData";
import type { CaseAnswer } from "@/lib/types";
import { SourceBadge, RouteBadge } from "./Badges";

const TONE_CLASS: Record<"fraud" | "clear" | "warn", string> = {
  fraud: "text-fraud glow-fraud",
  clear: "text-clear glow-clear",
  warn: "text-hold glow-hold",
};

const AUTO_ADVANCE_MS = 1400;

export function CaseReplay({
  cases,
}: {
  cases: { id: string; label: string; data: CaseAnswer }[];
}) {
  const [caseId, setCaseId] = useState(cases[0].id);
  const [stepIdx, setStepIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const reduce = useReducedMotion();
  const sliderId = useId();

  const active = cases.find((c) => c.id === caseId) ?? cases[0];
  const sequence = useMemo(() => buildReplaySequence(active.data), [active]);
  const maxIdx = sequence.steps.length - 1;

  // Re-derive from step 0 whenever the case changes.
  useEffect(() => {
    setStepIdx(0);
    setPlaying(false);
  }, [caseId]);

  // Auto-advance. Disabled entirely under reduced motion, per spec.
  useEffect(() => {
    if (!playing || reduce) return;
    if (stepIdx >= maxIdx) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setStepIdx((i) => Math.min(i + 1, maxIdx)), AUTO_ADVANCE_MS);
    return () => clearTimeout(t);
  }, [playing, stepIdx, maxIdx, reduce]);

  const step = sequence.steps[stepIdx];
  const band = probabilityBand(step.probability);
  const evidenceSoFar = sequence.steps.slice(0, stepIdx + 1).filter((s) => s.kind === "evidence");
  const flipReached = sequence.flipIndex !== null && stepIdx >= sequence.flipIndex;

  return (
    <section className="instrument p-4 sm:p-6" aria-label="Investigation replay">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg text-bright">Investigation replay</h2>
          <p className="mt-0.5 text-xs text-ink-dim">
            Drag the timeline to watch the agent&apos;s reasoning at that moment — recomputed
            from the case&apos;s real evidence, not replayed.
          </p>
        </div>
        <label className="flex items-center gap-2">
          <span className="readout text-[0.65rem] uppercase tracking-[0.12em] text-ink-faint">
            case
          </span>
          <select
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            className="readout rounded border border-seam-hi bg-deck px-2 py-1.5 text-xs text-ink focus-visible:outline-2 focus-visible:outline-phosphor"
          >
            {cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </header>

      {/* Readout: probability + verdict band. Every number here lives in .readout. */}
      <div className="mb-4 flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-2.5">
          <span className={`readout text-[2.75rem] leading-none font-medium ${TONE_CLASS[band.tone]}`}>
            {pct2(step.probability)}
          </span>
          <span className={`readout text-[0.7rem] uppercase tracking-[0.14em] ${TONE_CLASS[band.tone].split(" ")[0]}`}>
            {band.label}
          </span>
        </div>
        <span className="readout pb-1 text-[0.65rem] uppercase tracking-[0.14em] text-ink-faint">
          step {stepIdx + 1} / {sequence.steps.length}
        </span>
      </div>

      <Scrubber
        id={sliderId}
        steps={sequence.steps}
        value={stepIdx}
        onChange={setStepIdx}
        flipIndex={sequence.flipIndex}
        reduce={!!reduce}
      />

      <div className="mt-3 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          disabled={!!reduce}
          className="readout rounded border border-seam-hi bg-deck px-3 py-1.5 text-[0.7rem] uppercase tracking-[0.12em] text-ink-dim transition-colors hover:border-phosphor-lo hover:text-phosphor disabled:opacity-40"
          aria-label={playing ? "Pause auto-advance" : "Play auto-advance"}
        >
          {playing ? "⏸ pause" : "▶ play"}
        </button>
        <p className="readout text-[0.68rem] text-ink-faint">{step.label}</p>
      </div>

      {sequence.flipIndex !== null && (
        <p className="readout mt-2 text-[0.66rem] uppercase tracking-[0.1em] text-hold">
          {flipReached ? "recommendation flipped at this point ↑" : "recommendation flips further along →"}
        </p>
      )}

      {/* Evidence discovered so far. */}
      <div className="mt-5 border-t border-seam pt-4">
        <p className="readout mb-2.5 text-[0.64rem] uppercase tracking-[0.13em] text-ink-faint">
          evidence discovered ({evidenceSoFar.length})
        </p>
        {evidenceSoFar.length === 0 ? (
          <p className="text-sm text-ink-faint">No evidence surfaced yet.</p>
        ) : (
          <ul className="space-y-2">
            {evidenceSoFar.map((s, i) => (
              <li key={i} className="border-b border-seam px-1 py-2 last:border-b-0">
                <div className="flex items-start justify-between gap-3 min-w-0">
                  <p className="text-sm text-ink min-w-0 flex-1 break-words">{s.evidence!.claim}</p>
                  <SourceBadge source={s.evidence!.source} />
                </div>
                <p className="readout mt-1 text-[11px] text-ink-faint truncate max-w-full" title={s.evidence!.ref}>{s.evidence!.ref}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Evidence request, once revealed. */}
      {step.kind === "evidence_request" && step.request && (
        <div className="mt-4 rounded-[var(--r-md)] border border-phosphor-lo/40 bg-deck px-3 py-2.5">
          <div className="readout text-[0.66rem] uppercase tracking-[0.12em] text-phosphor">
            {step.request.type.replace(/_/g, " ")}
            <span className="ml-2 text-ink-faint">after step {step.request.asked_after_step}</span>
          </div>
          <p className="mt-1.5 text-[0.82rem] leading-relaxed text-ink">{step.request.assumed_response}</p>
        </div>
      )}

      {/* Recommendation at this moment. */}
      <div className="mt-5 border-t border-seam pt-4">
        <p className="readout mb-2.5 text-[0.64rem] uppercase tracking-[0.13em] text-ink-faint">
          recommendation at this step
        </p>
        <ol className="space-y-1.5">
          {step.recommendation.map((a) => (
            <li
              key={a.action}
              className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-[var(--r-md)] border border-seam bg-deck px-3 py-2"
            >
              <span className="readout text-[0.8rem] text-bright">{a.action}</span>
              <RouteBadge route={a.route} />
              <span className="w-full text-[0.74rem] leading-snug text-ink-dim">{a.reason}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Scrubber({
  id,
  steps,
  value,
  onChange,
  flipIndex,
  reduce,
}: {
  id: string;
  steps: { label: string; probability: number }[];
  value: number;
  onChange: (i: number) => void;
  flipIndex: number | null;
  reduce: boolean;
}) {
  const max = steps.length - 1;
  const pct = max === 0 ? 0 : (value / max) * 100;
  const flipPct = flipIndex !== null && max > 0 ? (flipIndex / max) * 100 : null;
  const trackRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  function setFromClientX(clientX: number) {
    const el = trackRef.current;
    if (!el || max === 0) return;
    const rect = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    onChange(Math.round(ratio * max));
  }

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (!draggingRef.current) return;
      setFromClientX(e.clientX);
    }
    function onUp() {
      draggingRef.current = false;
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [max]);

  return (
    <div className="relative pt-1" style={{ touchAction: "none" }}>
      <div
        ref={trackRef}
        className="relative h-8 cursor-pointer"
        onPointerDown={(e) => {
          draggingRef.current = true;
          setFromClientX(e.clientX);
        }}
      >
        {/* track */}
        <div className="absolute top-1/2 h-[3px] w-full -translate-y-1/2 rounded-full bg-ridge" />
        {/* filled portion, phosphor = live/interactive */}
        <div
          className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-phosphor"
          style={{ width: `${pct}%`, transition: reduce ? "none" : "width 80ms linear" }}
        />
        {/* flip marker */}
        {flipPct !== null && (
          <div
            className="absolute top-1/2 h-3 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-hold"
            style={{ left: `${flipPct}%` }}
            aria-hidden
            title="Recommendation flip point"
          />
        )}
        {/* step ticks */}
        {steps.map((_, i) => (
          <div
            key={i}
            className="absolute top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-seam-hi"
            style={{ left: `${max === 0 ? 0 : (i / max) * 100}%` }}
            aria-hidden
          />
        ))}
        {/* handle */}
        <div
          role="slider"
          id={id}
          tabIndex={0}
          aria-label="Investigation timeline"
          aria-valuemin={0}
          aria-valuemax={max}
          aria-valuenow={value}
          aria-valuetext={`Step ${value + 1} of ${steps.length}: ${steps[value].label}, probability ${steps[value].probability.toFixed(2)}`}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowUp") {
              e.preventDefault();
              onChange(Math.min(max, value + 1));
            } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
              e.preventDefault();
              onChange(Math.max(0, value - 1));
            } else if (e.key === "Home") {
              e.preventDefault();
              onChange(0);
            } else if (e.key === "End") {
              e.preventDefault();
              onChange(max);
            }
          }}
          className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-phosphor bg-deck focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-phosphor"
          style={{
            left: `${pct}%`,
            boxShadow: "0 0 10px 1px var(--phosphor)",
            transition: reduce ? "none" : "left 80ms linear",
          }}
        />
      </div>
    </div>
  );
}
