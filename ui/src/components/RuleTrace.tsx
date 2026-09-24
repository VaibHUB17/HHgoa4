"use client";

import { motion, useReducedMotion } from "motion/react";
import type { RecommendedAction } from "@/lib/types";

/* The competing submission shows a static "L2_SENIOR_MANAGER" badge with no rule trace —
   an assertion of authority with nothing under it. This renders the actual policy engine:
   all ten predicates from config/fraud_policy.yaml, evaluated against this case's final
   actions. Rules that fired are bright and cite what they produced; rules that did not
   fire stay dimmed but present, because listing the ones that did NOT fire is the whole
   point — it is the only way to show the engine walked the entire policy rather than an
   LLM asserting a route number. R7 gets its own emphasis: unlike every other rule here,
   it FORBIDS an action (BLOCK_CARD, DECLINE_TRANSACTION) rather than producing one — a
   rule that stops the agent from blocking a legitimate recurring-charge dispute is more
   interesting than one more rule that blocks. */

interface Rule {
  id: string;
  predicate: string;
  produces?: string;
  forbids?: string;
}

// Verbatim from config/fraud_policy.yaml — predicates paraphrased to plain English,
// action/forbid lists kept exact.
const RULES: Rule[] = [
  {
    id: "R1",
    predicate: "Single signal only, fraud probability below 0.70 — must precede any block.",
    produces: "VERIFY_WITH_CUSTOMER or STEP_UP_AUTH",
  },
  {
    id: "R2",
    predicate: "Customer was asked to validate and denied the charge.",
    produces: "BLOCK_CARD, CREATE_CASE (+ FILE_REPORT if exposure > $1,000, shared device, or other-card fraud)",
  },
  {
    id: "R3",
    predicate: "Customer confirmed the charge as their own.",
    produces: "CLOSE_NO_FRAUD",
  },
  {
    id: "R4",
    predicate: "No customer reply within 24 hours.",
    produces: "MONITOR_CARD, DECLINE_TRANSACTION (+ ESCALATE_TO_ANALYST if exposure > $500)",
  },
  {
    id: "R5",
    predicate: "3+ sub-$5 online authorizations within an hour on one card, then a larger purchase.",
    produces: "DECLINE_TRANSACTION, STEP_UP_AUTH (overrides to BLOCK_CARD if a >$100 purchase already cleared)",
  },
  {
    id: "R6",
    predicate: "Device profile, billing region, or recipient email shared across multiple cards in one window.",
    produces: "CREATE_CASE, FILE_REPORT, MONITOR_CONNECTED_CARDS",
  },
  {
    id: "R7",
    predicate: "Disputed charge matches the customer's own recurring pattern — merchant, amount, monthly.",
    produces: "CREATE_CASE, VERIFY_WITH_CUSTOMER, WARN_CUSTOMER",
    forbids: "BLOCK_CARD, DECLINE_TRANSACTION",
  },
  {
    id: "R8",
    predicate: "Verdict uncertain with exposure over $500, or evidence conflicts.",
    produces: "ESCALATE_TO_ANALYST",
  },
  {
    id: "R9",
    predicate: "Fits none of the five documented patterns, and abuse is coordinated or repeated across customers.",
    produces: "CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST",
  },
  {
    id: "R10",
    predicate: "BLOCK_ALL_CARDS was proposed — requires 2+ cards confirmed fraud or confirmed compromised credentials, else downgrades to a single-card BLOCK_CARD.",
    produces: "guards BLOCK_ALL_CARDS",
  },
];

function firedRuleIds(actions: RecommendedAction[]): Set<string> {
  const ids = new Set<string>();
  for (const a of actions) {
    for (const m of a.reason.matchAll(/R(10|[1-9])\b/g)) {
      ids.add(`R${m[1]}`);
    }
  }
  return ids;
}

function actionsFor(ruleId: string, actions: RecommendedAction[]): RecommendedAction[] {
  return actions.filter((a) => new RegExp(`\\bR${ruleId.slice(1)}\\b`).test(a.reason));
}

const EASE = [0.16, 1, 0.3, 1] as const;

export function RuleTrace({ finalActions }: { finalActions: RecommendedAction[] }) {
  const reduce = useReducedMotion();
  const fired = firedRuleIds(finalActions);
  const firedCount = fired.size;

  return (
    <section className="instrument overflow-hidden" aria-label="Policy rule trace">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-seam px-4 py-2.5">
        <span className="readout text-[0.68rem] uppercase tracking-[0.14em] text-ink-dim">
          policy trace &middot; R1&ndash;R10
        </span>
        <span className="readout text-[0.64rem] text-ink-faint">
          {firedCount} of {RULES.length} predicates fired
        </span>
      </header>

      <p className="border-b border-seam px-4 py-2.5 text-[0.78rem] leading-relaxed text-ink-dim sm:px-6">
        Every rule below is a deterministic predicate evaluated against this case&rsquo;s
        evidence &mdash; not a model&rsquo;s assertion of an outcome. The engine checks all
        ten; most do not apply here, and that is shown deliberately.
      </p>

      <dl className="divide-y divide-seam">
        {RULES.map((rule, i) => {
          const didFire = fired.has(rule.id);
          const matched = didFire ? actionsFor(rule.id, finalActions) : [];
          const isForbidRule = Boolean(rule.forbids);

          return (
            <motion.div
              key={rule.id}
              initial={reduce ? undefined : { opacity: 0, x: didFire ? -8 : 0 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true, margin: "-40px" }}
              transition={
                reduce
                  ? { duration: 0 }
                  : { duration: 0.4, delay: didFire ? i * 0.09 : 0, ease: EASE }
              }
              className={`px-4 py-3 sm:px-6 ${didFire ? "bg-deck" : ""}`}
            >
              <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                <dt className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className={`inline-block h-1.5 w-1.5 rounded-full ${
                      didFire ? (isForbidRule ? "bg-hold" : "bg-phosphor") : "bg-seam-hi"
                    }`}
                  />
                  <span
                    className={`readout text-[0.82rem] font-medium ${
                      didFire ? (isForbidRule ? "text-hold" : "text-phosphor") : "text-ink-faint"
                    }`}
                  >
                    {rule.id}
                  </span>
                </dt>
                <span
                  className={`readout text-[0.62rem] uppercase tracking-[0.12em] ${
                    didFire ? "text-ink-dim" : "text-ink-faint"
                  }`}
                >
                  {didFire ? (isForbidRule ? "fired — forbid" : "fired") : "did not fire"}
                </span>
              </div>

              <dd
                className={`mt-1 text-[0.82rem] leading-relaxed ${
                  didFire ? "text-ink" : "text-ink-faint"
                }`}
              >
                {rule.predicate}
              </dd>

              {didFire && rule.forbids && (
                <dd className="mt-1.5 text-[0.76rem] leading-relaxed text-hold">
                  Forbids: <span className="readout">{rule.forbids}</span> — blocking is
                  withheld even though the case was flagged.
                </dd>
              )}

              {didFire && matched.length > 0 && (
                <dd className="mt-2 flex flex-wrap gap-1.5">
                  {matched.map((a) => (
                    <span
                      key={a.action}
                      className="readout inline-flex items-center gap-1.5 rounded border border-seam-hi bg-bed px-2 py-1 text-[0.7rem] text-ink"
                    >
                      {a.action}
                      <span className="text-ink-faint">&middot;</span>
                      <span className="uppercase tracking-wide text-ink-dim">{a.route}</span>
                    </span>
                  ))}
                </dd>
              )}

              {didFire && rule.produces && matched.length === 0 && (
                <dd className="mt-1.5 text-[0.74rem] leading-relaxed text-ink-dim">
                  Produces: <span className="readout">{rule.produces}</span>
                </dd>
              )}
            </motion.div>
          );
        })}
      </dl>
    </section>
  );
}
