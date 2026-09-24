"use client";

import { motion, useReducedMotion } from "motion/react";
import type { CaseAnswer } from "@/lib/types";

// The README's schema gives similar_prior_cases as a flat list of closed-case IDs with no
// structured outcome field. We infer confirming vs. disconfirming from the evidence list:
// a prior case cited alongside language like "confirmed fraud" reads as confirming; one
// cited alongside "cleared" reads as disconfirming. Anything we can't classify from the
// evidence text is shown neutrally rather than guessed into either bucket.
function classify(caseId: string, evidence: CaseAnswer["case"]["evidence"]): "confirming" | "disconfirming" | "neutral" {
  const hit = evidence.find((e) => e.entity_ids.includes(caseId) || e.claim.includes(caseId));
  if (!hit) return "neutral";
  const text = hit.claim.toLowerCase();
  if (text.includes("cleared") || text.includes("legitimate")) return "disconfirming";
  if (text.includes("confirmed") || text.includes("fraud")) return "confirming";
  return "neutral";
}

const styleFor = {
  confirming: "border-fraud/40 bg-fraud/10 text-fraud",
  disconfirming: "border-clear/40 bg-clear/10 text-clear",
  neutral: "border-seam-hi bg-deck text-ink-dim",
} as const;

const labelFor = {
  confirming: "Supports fraud",
  disconfirming: "Exonerates",
  neutral: "Referenced",
} as const;

// Confirming and disconfirming cases enter from opposite directions — supporting evidence
// rises from below (weight added to the case), exonerating evidence settles from above
// (weight lifted) — so the opposition reads in the motion itself, not just the color.
const enterFor = {
  confirming: { y: 10, x: 0 },
  disconfirming: { y: -10, x: 0 },
  neutral: { y: 6, x: 0 },
};

function CaseChip({ id, kind, delay, reduce }: { id: string; kind: Kind; delay: number; reduce: boolean | null }) {
  return (
    <motion.li
      initial={reduce ? undefined : { opacity: 0, ...enterFor[kind] }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 280, damping: 24, delay }}
      className={`flex items-center justify-between gap-2 rounded border px-3 py-2 ${styleFor[kind]}`}
    >
      <span className="readout text-sm">{id}</span>
      <span className="readout text-[10px] uppercase tracking-wide">{labelFor[kind]}</span>
    </motion.li>
  );
}

type Kind = "confirming" | "disconfirming" | "neutral";

export function SimilarCases({ caseAnswer }: { caseAnswer: CaseAnswer }) {
  const reduce = useReducedMotion();
  const ids = caseAnswer.case.similar_prior_cases;
  if (ids.length === 0) {
    return <p className="text-sm text-ink-faint">No prior cases retrieved as memory.</p>;
  }

  const classified = ids.map((id) => ({ id, kind: classify(id, caseAnswer.case.evidence) }));
  const confirming = classified.filter((c) => c.kind === "confirming");
  const disconfirming = classified.filter((c) => c.kind === "disconfirming");
  const neutral = classified.filter((c) => c.kind === "neutral");

  // Confirming and disconfirming precedent sit in physically separate columns, divided by
  // a hairline, rather than interleaved in one grid — the opposition is a structural split,
  // not just a color difference between adjacent chips.
  return (
    <div>
      <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
        <div>
          <p className="mb-1.5 readout text-[10px] uppercase tracking-wide text-fraud/80">
            Confirming precedent
          </p>
          {confirming.length === 0 ? (
            <p className="text-xs text-ink-faint">None</p>
          ) : (
            <ul className="space-y-1.5">
              {confirming.map((c, i) => (
                <CaseChip key={c.id} id={c.id} kind={c.kind} delay={i * 0.05} reduce={reduce} />
              ))}
            </ul>
          )}
        </div>
        <div className="border-t border-seam pt-2 sm:border-t-0 sm:border-l sm:pl-4 sm:pt-0">
          <p className="mb-1.5 readout text-[10px] uppercase tracking-wide text-clear/80">
            Disconfirming precedent
          </p>
          {disconfirming.length === 0 ? (
            <p className="text-xs text-ink-faint">None</p>
          ) : (
            <ul className="space-y-1.5">
              {disconfirming.map((c, i) => (
                <CaseChip key={c.id} id={c.id} kind={c.kind} delay={i * 0.05} reduce={reduce} />
              ))}
            </ul>
          )}
        </div>
      </div>
      {neutral.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5 border-t border-seam pt-2.5">
          {neutral.map((c, i) => (
            <CaseChip key={c.id} id={c.id} kind={c.kind} delay={i * 0.03} reduce={reduce} />
          ))}
        </ul>
      )}
    </div>
  );
}
