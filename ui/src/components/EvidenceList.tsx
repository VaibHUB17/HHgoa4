"use client";

import { motion, useReducedMotion } from "motion/react";
import type { EvidenceItem, EvidenceSource } from "@/lib/types";
import { SourceBadge } from "./Badges";

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

// Each source type arrives from a different direction, so the list reads as
// evidence converging from distinct places rather than one uniform reveal.
// Graph evidence comes from the network (from the right, where the graph
// views live in this console); documents rise from below like a filed sheet;
// customer evidence slides in from the left, closest to the human account.
const directionBySource: Record<EvidenceSource, { x: number; y: number }> = {
  graph: { x: 14, y: 0 },
  document: { x: 0, y: 12 },
  customer: { x: -14, y: 0 },
  external: { x: 0, y: -10 },
};

function itemVariants(source: EvidenceSource) {
  const d = directionBySource[source];
  return {
    hidden: { opacity: 0, x: d.x, y: d.y },
    show: { opacity: 1, x: 0, y: 0 },
  };
}

export function EvidenceList({ evidence }: { evidence: EvidenceItem[] }) {
  const reduce = useReducedMotion();

  if (evidence.length === 0) {
    return <p className="text-sm text-ink-faint">No evidence recorded.</p>;
  }

  return (
    <motion.ul
      className="space-y-2 min-w-0"
      variants={reduce ? undefined : container}
      initial={reduce ? undefined : "hidden"}
      whileInView={reduce ? undefined : "show"}
      viewport={{ once: true, margin: "-40px" }}
    >
      {evidence.map((e, i) => (
        <motion.li
          key={i}
          variants={reduce ? undefined : itemVariants(e.source)}
          transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 300, damping: 26 }}
          className="border-b border-seam px-1 py-2.5 last:border-b-0 min-w-0 overflow-hidden"
        >
          <div className="flex items-start justify-between gap-3 min-w-0">
            <p className="text-sm text-ink min-w-0 flex-1 break-words">{e.claim}</p>
            <SourceBadge source={e.source} />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-faint min-w-0">
            <span className="readout truncate max-w-full" title={e.ref}>{e.ref}</span>
            {e.entity_ids.length > 0 && (
              <span className="flex flex-wrap gap-1 max-w-full">
                {e.entity_ids.map((id) => (
                  <span
                    key={id}
                    className="rounded bg-void px-1.5 py-0.5 readout text-ink-dim shrink-0"
                  >
                    {id}
                  </span>
                ))}
              </span>
            )}
          </div>
        </motion.li>
      ))}
    </motion.ul>
  );
}
