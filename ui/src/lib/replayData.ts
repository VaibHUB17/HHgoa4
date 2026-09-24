// Derives a scrubbable step sequence from a real case JSON (cases/<id>.json).
//
// Nothing here is animation-authored. Each step is one real record — an
// evidence item, or the evidence request — in the order the case file
// already puts them (evidence[] array order, evidence_requests[].asked_after_step
// for where the request lands). The probability at each step is recomputed
// from evidence_weights.yaml's own formula (sigmoid of summed weights of
// evidence keys present so far), not interpolated toward the final number.
//
// Matching a free-text claim to a weight key is inherently a heuristic (the
// case JSON stores prose, not the weight key), so we match on the same
// vocabulary the agent's own claim templates use (see cases/*.json claim
// strings) and keep the table 1:1 with evidence_weights.yaml's comments.
// The LAST step is always pinned to the case's real final fraud_probability,
// so the sequence can drift slightly mid-way (an honest approximation of an
// internal calculation we don't have logged step-by-step) but always lands
// exactly on the ground truth.

import type { CaseAnswer, EvidenceItem, EvidenceRequest, RecommendedAction } from "./types";


/* The replay cases are passed in from the server component that already loads
   cases/, rather than imported here. Importing JSON from outside the ui/ project
   root cannot be resolved by the bundler in a client component, and reaching
   across the root for data is the wrong seam anyway. */
export const REPLAY_LABELS: Record<string, string> = {
  "HHG-017": "HHG-017 · card testing",
  "HHG-006": "HHG-006 · undocumented pattern",
  "HHG-014": "HHG-014 · 17-card device ring",
  "HHG-003": "HHG-003 · legitimate",
};

export const REPLAY_IDS = ["HHG-017", "HHG-006", "HHG-014", "HHG-003"];

export function buildReplayCases(
  all: CaseAnswer[],
): { id: string; label: string; data: CaseAnswer }[] {
  return REPLAY_IDS.map((id) => {
    const data = all.find((c) => c.case_id === id);
    return data ? { id, label: REPLAY_LABELS[id] ?? id, data } : null;
  }).filter((x): x is { id: string; label: string; data: CaseAnswer } => x !== null);
}

// Verbatim from config/evidence_weights.yaml (frozen contract — see that file's header).
const WEIGHTS = {
  card_testing_sequence: 0.35,
  shared_device_across_cards: 0.3,
  customer_denies: 0.3,
  shared_region_cluster: 0.25,
  cnp_burst_pattern: 0.2,
  out_of_region_pattern: 0.2,
  multi_region_clone_cluster: 0.15,
  closed_case_match: 0.2,
  new_device_marker: 0.15,
  proxy_flag: 0.1,
  risk_score_alone: 0.05,
  recurring_merchant_match: -0.25,
  cleared_precedent_match: -0.2,
  in_character_for_customer: -0.2,
  customer_confirms: -0.9,
  step_up_failed: 0.2,
  step_up_not_completed: 0.05,
  step_up_passed: -0.2,
} as const;

type WeightKey = keyof typeof WEIGHTS;

// Maps an evidence claim's real vocabulary to the weight key it evidences.
// Order matters: first match wins, most specific pattern first.
const CLAIM_MATCHERS: [RegExp, WeightKey][] = [
  [/structuring|just under \$?\d|threshold/i, "card_testing_sequence"],
  [/sub-\$5|within (1 ?hour|1hr|1 hr)/i, "card_testing_sequence"],
  [/shared device profile.*distinct customers|used by \d+ distinct customers/i, "shared_device_across_cards"],
  [/shared-device cluster|device.*cluster spanning/i, "shared_device_across_cards"],
  [/also used on connected card/i, "shared_device_across_cards"],
  [/structural match.*shared device\/region\/card.*confirmed_fraud|closed case.*fraud/i, "closed_case_match"],
  [/structural match.*cleared closed case|cleared closed case/i, "cleared_precedent_match"],
  [/marked 'new' for this account|id_15 ?== ?new|device marked 'new'/i, "new_device_marker"],
  [/recurring merchant\/amount pattern|recurring monthly (charge|subscription)/i, "recurring_merchant_match"],
  [/matches this customer's established history|in-character|established history/i, "in_character_for_customer"],
  [/model risk score|risk score \d.*no other corroborating/i, "risk_score_alone"],
  [/proxy|anonymous|hidden.*id_23/i, "proxy_flag"],
  [/out.of.region|billing region outside/i, "out_of_region_pattern"],
];

export interface ReplayStep {
  index: number;
  kind: "evidence" | "evidence_request";
  label: string;
  evidence?: EvidenceItem;
  request?: EvidenceRequest;
  matchedKey?: WeightKey;
  probability: number;
  recommendation: RecommendedAction[];
  isFlipPoint: boolean;
}

export interface ReplaySequence {
  caseId: string;
  steps: ReplayStep[];
  flipIndex: number | null; // step index where recommendation first changed, or null
  finalProbability: number;
}

function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-x));
}

function matchClaim(claim: string): WeightKey | undefined {
  for (const [re, key] of CLAIM_MATCHERS) {
    if (re.test(claim)) return key;
  }
  return undefined;
}

// The evidence request's own resolution (assumed_response) reads as a
// customer confirm/deny, or a step-up outcome — same vocabulary the case
// summaries and what_changed strings use.
function matchRequestOutcome(req: EvidenceRequest): WeightKey | undefined {
  const text = req.assumed_response.toLowerCase();
  if (req.type === "customer_validation") {
    if (/does not dispute|confirms they made|recognizing/.test(text)) return "customer_confirms";
    if (/did not make|do not recognize|denies/.test(text)) return "customer_denies";
  }
  if (req.type === "step_up_auth") {
    if (/passed|completed|valid otp/.test(text)) return "step_up_passed";
    if (/expired|unanswered/.test(text)) return "step_up_not_completed";
    if (/failed|not completed/.test(text)) return "step_up_failed";
  }
  return undefined;
}

export function buildReplaySequence(answer: CaseAnswer): ReplaySequence {
  const { case: c, evidence_requests, next_best_actions } = answer;

  // Interleave evidence items with evidence requests at their real position
  // (asked_after_step is 1-indexed into the evidence array, per case files).
  type Entry =
    | { kind: "evidence"; evidence: EvidenceItem }
    | { kind: "evidence_request"; request: EvidenceRequest };

  const entries: Entry[] = [];
  const requestsByStep = new Map<number, EvidenceRequest[]>();
  for (const r of evidence_requests) {
    const arr = requestsByStep.get(r.asked_after_step) ?? [];
    arr.push(r);
    requestsByStep.set(r.asked_after_step, arr);
  }

  c.evidence.forEach((ev, i) => {
    entries.push({ kind: "evidence", evidence: ev });
    const stepNum = i + 1;
    for (const r of requestsByStep.get(stepNum) ?? []) {
      entries.push({ kind: "evidence_request", request: r });
    }
  });
  // Any requests whose asked_after_step exceeds the evidence count land at the end.
  for (const [stepNum, reqs] of requestsByStep) {
    if (stepNum > c.evidence.length) entries.push(...reqs.map((request) => ({ kind: "evidence_request" as const, request })));
  }

  let runningSum = 0;
  let requestSeen = false;
  let flipIndex: number | null = null;
  const steps: ReplayStep[] = [];

  entries.forEach((entry, i) => {
    const isLast = i === entries.length - 1;

    if (entry.kind === "evidence") {
      const key = matchClaim(entry.evidence.claim);
      if (key) runningSum += WEIGHTS[key];
      const recommendation = requestSeen ? next_best_actions.final : next_best_actions.initial;
      steps.push({
        index: i,
        kind: "evidence",
        label: `Evidence ${steps.filter((s) => s.kind === "evidence").length + 1}`,
        evidence: entry.evidence,
        matchedKey: key,
        probability: isLast ? c.fraud_probability : sigmoid(runningSum),
        recommendation,
        isFlipPoint: false,
      });
    } else {
      const key = matchRequestOutcome(entry.request);
      if (key) runningSum += WEIGHTS[key];
      requestSeen = true;
      // The moment the recommendation set actually differs from initial.
      const changed =
        next_best_actions.what_changed !== "nothing" &&
        JSON.stringify(next_best_actions.initial.map((a) => a.action).sort()) !==
          JSON.stringify(next_best_actions.final.map((a) => a.action).sort());
      if (changed && flipIndex === null) flipIndex = i;
      steps.push({
        index: i,
        kind: "evidence_request",
        label: `Evidence requested: ${entry.request.type.replace(/_/g, " ")}`,
        request: entry.request,
        matchedKey: key,
        probability: isLast ? c.fraud_probability : sigmoid(runningSum),
        recommendation: next_best_actions.final,
        isFlipPoint: changed,
      });
    }
  });

  // No evidence at all (shouldn't happen in real cases, but keep the sequence valid).
  if (steps.length === 0) {
    steps.push({
      index: 0,
      kind: "evidence",
      label: "No evidence recorded",
      probability: c.fraud_probability,
      recommendation: next_best_actions.final,
      isFlipPoint: false,
    });
  }

  return {
    caseId: answer.case_id,
    steps,
    flipIndex,
    finalProbability: c.fraud_probability,
  };
}
