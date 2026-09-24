"use client";

import { useState } from "react";
import { motion, useReducedMotion, AnimatePresence } from "motion/react";
import type { RecommendedAction } from "@/lib/types";
import { RouteBadge } from "./Badges";

type Decision = "pending" | "approved" | "rejected";

const PRESS_SPRING = { type: "spring", stiffness: 500, damping: 18, mass: 0.5 } as const;

// A human decision point. L1/L2 actions are pending until an analyst clicks one of these —
// keyboard-operable (real <button>s, visible focus ring from globals.css :focus-visible),
// and the resulting state is announced via aria-live so a screen reader user gets the outcome.
export function ApprovalControl({ action }: { action: RecommendedAction }) {
  const [decision, setDecision] = useState<Decision>("pending");
  const reduce = useReducedMotion();

  return (
    <motion.div
      layout
      className={`flex items-center justify-between gap-3 rounded-lg border border-seam-hi bg-deck px-3 py-2.5 ${
        decision === "pending" ? "awaiting" : ""
      }`}
      // The decision landing: a settle-and-flash on the whole control, as if the
      // card just took a physical hit, not just a text swap in a corner of it.
      animate={
        !reduce && decision !== "pending"
          ? {
              scale: [1, 0.985, 1],
              borderColor: [
                "var(--seam-hi)",
                decision === "approved" ? "var(--clear)" : "var(--fraud)",
                "var(--seam-hi)",
              ],
            }
          : undefined
      }
      transition={reduce ? { duration: 0 } : { duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="readout text-sm text-bright">{action.action}</span>
          <RouteBadge route={action.route} />
        </div>
        <p className="mt-0.5 text-xs text-ink-dim">{action.reason}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <AnimatePresence mode="wait" initial={false}>
          {decision === "pending" ? (
            <motion.div
              key="controls"
              className="flex items-center gap-1.5"
              initial={reduce ? undefined : { opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={reduce ? undefined : { opacity: 0 }}
            >
              <motion.button
                type="button"
                onClick={() => setDecision("approved")}
                whileTap={reduce ? undefined : { scale: 0.97 }}
                transition={PRESS_SPRING}
                className="rounded border border-clear/50 bg-clear/10 px-2.5 py-1 font-body text-xs font-medium text-clear transition-colors hover:bg-clear/20 focus-visible:outline-2 focus-visible:outline-phosphor"
              >
                Approve
              </motion.button>
              <motion.button
                type="button"
                onClick={() => setDecision("rejected")}
                whileTap={reduce ? undefined : { scale: 0.97 }}
                transition={PRESS_SPRING}
                className="rounded border border-fraud/50 bg-fraud/10 px-2.5 py-1 font-body text-xs font-medium text-fraud transition-colors hover:bg-fraud/20 focus-visible:outline-2 focus-visible:outline-phosphor"
              >
                Reject
              </motion.button>
            </motion.div>
          ) : (
            <motion.span
              key="result"
              role="status"
              aria-live="polite"
              initial={reduce ? undefined : { opacity: 0, scale: 1.3, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 380, damping: 15, mass: 0.7 }}
              className={`rounded border px-2.5 py-1 readout text-xs uppercase tracking-wide ${
                decision === "approved"
                  ? "border-clear/40 bg-clear/10 text-clear"
                  : "border-fraud/40 bg-fraud/10 text-fraud"
              }`}
            >
              {decision === "approved" ? "Approved" : "Rejected"}
            </motion.span>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
