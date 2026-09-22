"use client";

import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import type { RecommendedAction, EvidenceRequest } from "@/lib/types";
import { ApprovalControl } from "./ApprovalControl";
import { RouteBadge } from "./Badges";

// The single most load-bearing view in the app: initial vs final recommendation, with the
// evidence_requests that caused the change sitting on the spine between them as the causal
// link. Unchanged actions render static (no motion — the eye should only be drawn to what
// evidence actually changed). Removed actions strike through and fade in place. Added actions
// arrive with a spring from the spine side. useReducedMotion() collapses all of this to an
// instant opacity swap.

function actionKey(a: RecommendedAction) {
  return a.action;
}

function diffActions(initial: RecommendedAction[], final: RecommendedAction[]) {
  const initialKeys = new Set(initial.map(actionKey));
  const finalKeys = new Set(final.map(actionKey));
  return {
    removed: initial.filter((a) => !finalKeys.has(actionKey(a))),
    added: final.filter((a) => !initialKeys.has(actionKey(a))),
    kept: final.filter((a) => initialKeys.has(actionKey(a))),
  };
}

function ActionRow({
  action,
  state,
}: {
  action: RecommendedAction;
  state: "kept" | "removed" | "added";
}) {
  const reduce = useReducedMotion();
  const isAuto = action.route === "auto";

  const content = (
    <div
      className={`rounded-lg border px-3 py-2.5 ${
        state === "removed"
          ? "border-line bg-panel/40 opacity-50"
          : "border-line-hi bg-panel-hi"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`font-data text-sm ${state === "removed" ? "text-faint line-through" : "text-paper"}`}
        >
          {action.action}
        </span>
        <RouteBadge route={action.route} />
        {isAuto && state !== "removed" && (
          <span className="rounded bg-clear/10 px-1.5 py-0.5 font-data text-[10px] uppercase tracking-wide text-clear">
            Executed
          </span>
        )}
      </div>
      <p className={`mt-0.5 text-xs ${state === "removed" ? "text-faint" : "text-dim"}`}>
        {action.reason}
      </p>
      {!isAuto && state !== "removed" && (
        <div className="mt-2">
          <ApprovalControl action={action} />
        </div>
      )}
    </div>
  );

  if (state === "added") {
    return (
      <motion.div
        layout
        initial={reduce ? undefined : { opacity: 0, x: -16, scale: 0.98 }}
        animate={{ opacity: 1, x: 0, scale: 1 }}
        transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 24 }}
      >
        {content}
      </motion.div>
    );
  }

  return <div>{content}</div>;
}

export function RecommendationDelta({
  initial,
  final,
  whatChanged,
  evidenceRequests,
}: {
  initial: RecommendedAction[];
  final: RecommendedAction[];
  whatChanged: string;
  evidenceRequests: EvidenceRequest[];
}) {
  const nothingChanged = whatChanged === "nothing";
  const { removed, added, kept } = diffActions(initial, final);

  return (
    <div>
      <div className="grid grid-cols-[1fr_auto_1fr] gap-4">
        {/* Initial column */}
        <div>
          <h3 className="mb-2 font-data text-xs uppercase tracking-wide text-faint">
            Initial recommendation
          </h3>
          <div className="space-y-2">
            {initial.map((a) => (
              <ActionRow
                key={actionKey(a)}
                action={a}
                state={removed.some((r) => actionKey(r) === actionKey(a)) ? "removed" : "kept"}
              />
            ))}
          </div>
        </div>

        {/* Spine */}
        <div className="flex flex-col items-center">
          <div className="h-3" />
          <div className="w-px flex-1 bg-line-hi" aria-hidden />
          {evidenceRequests.length > 0 && (
            <div className="my-3 max-w-[220px] rounded-lg border border-signal/40 bg-signal/10 px-3 py-2 text-center">
              <p className="font-data text-[10px] uppercase tracking-wide text-signal">
                Evidence requested
              </p>
              {evidenceRequests.map((er, i) => (
                <p key={i} className="mt-1 text-[11px] leading-snug text-paper/90">
                  <span className="text-faint">{er.type.replace(/_/g, " ")}:</span>{" "}
                  {er.assumed_response}
                </p>
              ))}
            </div>
          )}
          <div className="w-px flex-1 bg-line-hi" aria-hidden />
          <div className="h-3" />
        </div>

        {/* Final column */}
        <div>
          <h3 className="mb-2 font-data text-xs uppercase tracking-wide text-faint">
            Final recommendation
          </h3>
          <div className="space-y-2">
            <AnimatePresence initial={false}>
              {[...kept, ...added].map((a) => (
                <ActionRow
                  key={actionKey(a)}
                  action={a}
                  state={added.some((r) => actionKey(r) === actionKey(a)) ? "added" : "kept"}
                />
              ))}
            </AnimatePresence>
          </div>
        </div>
      </div>

      <div
        className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
          nothingChanged
            ? "border-line-hi bg-panel-hi text-dim"
            : "border-signal/30 bg-signal/5 text-paper"
        }`}
      >
        <span className="mr-2 font-data text-xs uppercase tracking-wide text-signal">
          What changed
        </span>
        {whatChanged}
      </div>
    </div>
  );
}
