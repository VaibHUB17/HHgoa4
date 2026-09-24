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
  neutral: "border-line-hi bg-panel-hi text-dim",
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

export function SimilarCases({ caseAnswer }: { caseAnswer: CaseAnswer }) {
  const reduce = useReducedMotion();
  const ids = caseAnswer.case.similar_prior_cases;
  if (ids.length === 0) {
    return <p className="text-sm text-faint">No prior cases retrieved as memory.</p>;
  }
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {ids.map((id, i) => {
        const kind = classify(id, caseAnswer.case.evidence);
        return (
          <motion.li
            key={id}
            initial={reduce ? undefined : { opacity: 0, ...enterFor[kind] }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-40px" }}
            transition={
              reduce ? { duration: 0 } : { type: "spring", stiffness: 280, damping: 24, delay: i * 0.05 }
            }
            className={`rounded-lg border px-3 py-2 ${styleFor[kind]}`}
          >
            <div className="flex items-center justify-between">
              <span className="font-data text-sm">{id}</span>
              <span className="font-data text-[10px] uppercase tracking-wide">
                {labelFor[kind]}
              </span>
            </div>
          </motion.li>
        );
      })}
    </ul>
  );
}
