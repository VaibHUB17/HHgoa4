"use client";

import { motion, useReducedMotion } from "motion/react";
import type { EvidenceItem } from "@/lib/types";
import { SourceBadge } from "./Badges";

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0 },
};

export function EvidenceList({ evidence }: { evidence: EvidenceItem[] }) {
  const reduce = useReducedMotion();

  if (evidence.length === 0) {
    return <p className="text-sm text-faint">No evidence recorded.</p>;
  }

  return (
    <motion.ul
      className="space-y-2"
      variants={reduce ? undefined : container}
      initial={reduce ? undefined : "hidden"}
      whileInView={reduce ? undefined : "show"}
      viewport={{ once: true, margin: "-40px" }}
    >
      {evidence.map((e, i) => (
        <motion.li
          key={i}
          variants={reduce ? undefined : item}
          transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 300, damping: 26 }}
          className="rounded-lg border border-line-hi bg-panel-hi px-3 py-2.5"
        >
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-paper">{e.claim}</p>
            <SourceBadge source={e.source} />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
            <span className="font-data">{e.ref}</span>
            {e.entity_ids.length > 0 && (
              <span className="flex flex-wrap gap-1">
                {e.entity_ids.map((id) => (
                  <span
                    key={id}
                    className="rounded bg-slate px-1.5 py-0.5 font-data text-dim"
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
