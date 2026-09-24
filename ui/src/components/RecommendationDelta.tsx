"use client";

import { motion, useReducedMotion } from "motion/react";
import type { RecommendedAction, EvidenceRequest } from "@/lib/types";
import { ApprovalControl } from "./ApprovalControl";
import { RouteBadge } from "./Badges";

/* The recommendation history — the single most load-bearing view here.

   The brief requires the next best action recorded before evidence is requested
   AND after it arrives, because that is what proves the agent revises its
   judgement rather than deciding once. Two columns side by side state that a
   change happened; they do not show it being caused.

   So this is built as a vertical chain read top to bottom: what we recommended,
   what we went and asked, what came back, what we recommend now. The evidence
   request sits ON the spine between the two states, because it is the cause. A
   pulse travels down that spine into the revised actions.

   Actions that survived the change are deliberately still. Only what actually
   moved is animated — if everything moves, nothing reads as having changed. */

function diffActions(initial: RecommendedAction[], final: RecommendedAction[]) {
  const initialNames = new Set(initial.map((a) => a.action));
  const finalNames = new Set(final.map((a) => a.action));
  return {
    removed: initial.filter((a) => !finalNames.has(a.action)),
    added: final.filter((a) => !initialNames.has(a.action)),
    kept: final.filter((a) => initialNames.has(a.action)),
  };
}

const EASE = [0.16, 1, 0.3, 1] as const;

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
  const reduce = useReducedMotion();
  const nothingChanged = whatChanged === "nothing";
  const { removed, added } = diffActions(initial, final);
  const hasChange = !nothingChanged && (removed.length > 0 || added.length > 0);

  return (
    <section className="instrument overflow-hidden" aria-label="Recommendation history">
      <header className="flex items-baseline justify-between border-b border-seam px-4 py-2.5">
        <span className="readout text-[0.68rem] uppercase tracking-[0.14em] text-ink-dim">
          recommendation history
        </span>
        <span className="readout text-[0.68rem] text-ink-faint">
          {hasChange ? "revised after evidence" : "unchanged"}
        </span>
      </header>

      <div className="relative px-4 py-5 sm:px-6">
        {/* The spine. Everything hangs off it, so the sequence reads as one
            movement rather than three stacked panels. */}
        <div className="absolute bottom-6 left-[calc(1rem+7px)] top-6 w-px bg-seam sm:left-[calc(1.5rem+7px)]" />
        {hasChange && !reduce && (
          <motion.div
            className="absolute left-[calc(1rem+5px)] h-5 w-[5px] rounded-full sm:left-[calc(1.5rem+5px)]"
            style={{
              background: "var(--phosphor)",
              boxShadow: "0 0 14px 2px var(--phosphor)",
            }}
            initial={{ top: "1.5rem", opacity: 0 }}
            animate={{ top: ["1.5rem", "calc(100% - 3rem)"], opacity: [0, 1, 1, 0] }}
            transition={{ duration: 1.5, delay: 0.5, ease: EASE, times: [0, 0.12, 0.8, 1] }}
          />
        )}

        <Stage
          marker="before"
          title="Initial recommendation"
          sub="on the evidence gathered so far"
          delay={0}
          reduce={reduce}
        >
          <ActionList actions={initial} state={hasChange ? "superseded" : "plain"} />
        </Stage>

        {evidenceRequests.length > 0 && (
          <Stage
            marker="ask"
            title="Evidence requested"
            sub={`${evidenceRequests.length} request${evidenceRequests.length === 1 ? "" : "s"}`}
            delay={0.18}
            reduce={reduce}
            accent
          >
            <ul className="space-y-2.5">
              {evidenceRequests.map((r, i) => (
                <li
                  key={i}
                  className="rounded-[var(--r-md)] border border-phosphor-lo/40 bg-deck px-3 py-2.5"
                >
                  <div className="readout text-[0.66rem] uppercase tracking-[0.12em] text-phosphor">
                    {r.type.replace(/_/g, " ")}
                    <span className="ml-2 text-ink-faint">after step {r.asked_after_step}</span>
                  </div>
                  <p className="mt-1.5 text-[0.82rem] leading-relaxed text-ink">
                    {r.assumed_response}
                  </p>
                </li>
              ))}
            </ul>
          </Stage>
        )}

        <Stage
          marker="after"
          title={hasChange ? "Revised recommendation" : "Final recommendation"}
          sub={hasChange ? "after the response came back" : "no revision required"}
          delay={0.34}
          reduce={reduce}
          last
        >
          <ActionList
            actions={final}
            state="plain"
            addedNames={new Set(added.map((a) => a.action))}
            animateFrom={0.5}
            reduce={reduce}
          />

          {removed.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {removed.map((a) => (
                <li
                  key={a.action}
                  className="flex items-center gap-2 text-[0.75rem] text-ink-faint line-through decoration-ink-faint/50"
                >
                  <span className="readout">{a.action}</span>
                  <span className="not-italic no-underline">withdrawn</span>
                </li>
              ))}
            </ul>
          )}

          <p
            className={`mt-4 border-l-0 text-[0.84rem] leading-relaxed ${
              hasChange ? "text-ink" : "text-ink-dim"
            }`}
          >
            {nothingChanged
              ? "The evidence settled the question without changing the recommended course of action."
              : whatChanged}
          </p>
        </Stage>
      </div>

      {/* The approval gate. Only L1/L2 actions surface here — `auto` actions the
          agent is permitted to execute itself would be noise, and showing them
          alongside would blur the very distinction this panel exists to make. */}
      {final.some((a) => a.route !== "auto") && (
        <div className="border-t border-seam bg-bed/60 px-4 py-4 sm:px-6">
          <p className="readout mb-2.5 text-[0.64rem] uppercase tracking-[0.13em] text-ink-faint">
            awaiting human approval
          </p>
          <div className="space-y-2">
            {final
              .filter((a) => a.route !== "auto")
              .map((a) => (
                <ApprovalControl key={a.action} action={a} />
              ))}
          </div>
        </div>
      )}
    </section>
  );
}

function Stage({
  marker,
  title,
  sub,
  children,
  delay,
  reduce,
  accent,
  last,
}: {
  marker: string;
  title: string;
  sub: string;
  children: React.ReactNode;
  delay: number;
  reduce: boolean | null;
  accent?: boolean;
  last?: boolean;
}) {
  return (
    <motion.div
      className={`relative pl-8 sm:pl-10 ${last ? "" : "pb-7"}`}
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={reduce ? undefined : { opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: EASE }}
    >
      {/* node on the spine */}
      <span
        aria-hidden
        className="absolute left-0 top-[5px] grid h-[15px] w-[15px] place-items-center rounded-full border"
        style={{
          background: accent ? "var(--phosphor)" : "var(--deck)",
          borderColor: accent ? "var(--phosphor)" : "var(--seam-hi)",
          boxShadow: accent ? "0 0 12px 1px var(--phosphor)" : undefined,
        }}
      >
        <span
          className="h-[5px] w-[5px] rounded-full"
          style={{ background: accent ? "var(--void)" : "var(--ink-faint)" }}
        />
      </span>

      <div className="mb-2.5 flex flex-wrap items-baseline gap-x-2.5">
        <h3 className="text-[0.92rem] font-medium text-bright">{title}</h3>
        <span className="readout text-[0.64rem] uppercase tracking-[0.12em] text-ink-faint">
          {marker} · {sub}
        </span>
      </div>
      {children}
    </motion.div>
  );
}

function ActionList({
  actions,
  state,
  addedNames,
  animateFrom,
  reduce,
}: {
  actions: RecommendedAction[];
  state: "plain" | "superseded";
  addedNames?: Set<string>;
  animateFrom?: number;
  reduce?: boolean | null;
}) {
  if (actions.length === 0) {
    return <p className="text-[0.82rem] text-ink-faint">No action recommended.</p>;
  }

  return (
    <ol className="space-y-1.5">
      {actions.map((a, i) => {
        const isNew = addedNames?.has(a.action) ?? false;
        const dim = state === "superseded";

        return (
          <motion.li
            key={a.action}
            className={`flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-[var(--r-md)] border px-3 py-2 ${
              isNew
                ? "border-phosphor-lo/55 bg-deck"
                : dim
                  ? "border-seam/60 bg-bed/60"
                  : "border-seam bg-deck"
            }`}
            initial={reduce || !isNew ? false : { opacity: 0, x: -8 }}
            animate={reduce || !isNew ? undefined : { opacity: 1, x: 0 }}
            transition={{
              type: "spring",
              stiffness: 300,
              damping: 26,
              delay: (animateFrom ?? 0) + i * 0.1,
            }}
          >
            <span
              className={`readout text-[0.8rem] ${
                isNew ? "text-phosphor" : dim ? "text-ink-dim" : "text-bright"
              }`}
            >
              {a.action}
            </span>
            <RouteBadge route={a.route} />
            {isNew && (
              <span className="readout text-[0.6rem] uppercase tracking-[0.12em] text-phosphor">
                new
              </span>
            )}
            <span className="w-full text-[0.74rem] leading-snug text-ink-dim">{a.reason}</span>
          </motion.li>
        );
      })}
    </ol>
  );
}
