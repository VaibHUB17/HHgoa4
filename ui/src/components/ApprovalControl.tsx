"use client";

import { useState } from "react";
import { motion, useReducedMotion, AnimatePresence } from "motion/react";
import type { RecommendedAction } from "@/lib/types";
import { RouteBadge } from "./Badges";

type Decision = "pending" | "approved" | "rejected";

// A human decision point. L1/L2 actions are pending until an analyst clicks one of these —
// keyboard-operable (real <button>s, visible focus ring from globals.css :focus-visible),
// and the resulting state is announced via aria-live so a screen reader user gets the outcome.
export function ApprovalControl({ action }: { action: RecommendedAction }) {
  const [decision, setDecision] = useState<Decision>("pending");
  const reduce = useReducedMotion();

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-line-hi bg-panel-hi px-3 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-data text-sm text-paper">{action.action}</span>
          <RouteBadge route={action.route} />
        </div>
        <p className="mt-0.5 text-xs text-dim">{action.reason}</p>
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
              <button
                type="button"
                onClick={() => setDecision("approved")}
                className="rounded border border-clear/50 bg-clear/10 px-2.5 py-1 font-body text-xs font-medium text-clear transition-colors hover:bg-clear/20 focus-visible:outline-2 focus-visible:outline-signal"
              >
                Approve
              </button>
              <button
                type="button"
                onClick={() => setDecision("rejected")}
                className="rounded border border-fraud/50 bg-fraud/10 px-2.5 py-1 font-body text-xs font-medium text-fraud transition-colors hover:bg-fraud/20 focus-visible:outline-2 focus-visible:outline-signal"
              >
                Reject
              </button>
            </motion.div>
          ) : (
            <motion.span
              key="result"
              role="status"
              aria-live="polite"
              initial={reduce ? undefined : { opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 300, damping: 20 }}
              className={`rounded border px-2.5 py-1 font-data text-xs uppercase tracking-wide ${
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
    </div>
  );
}
