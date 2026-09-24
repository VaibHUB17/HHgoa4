/* Faithful TypeScript port of src/policy/ledger.py + src/policy/engine.py.
 *
 * Every constant below is copied verbatim from the Python. This file has no
 * business logic of its own — it is a mirror, kept honest by selfCheck()
 * below, which re-derives the same anchor cases the Python docstrings and
 * demo()/tests assert.
 */

// --- evidence_weights.yaml, verbatim (config/evidence_weights.yaml) ------------------

export const EVIDENCE_WEIGHTS = {
  card_testing_sequence: 0.35, // R5
  shared_device_across_cards: 0.3, // R6
  customer_denies: 0.3, // R2
  shared_region_cluster: 0.25, // R6
  cnp_burst_pattern: 0.2,
  out_of_region_pattern: 0.2,
  multi_region_clone_cluster: 0.15,
  closed_case_match: 0.2,
  new_device_marker: 0.15,
  proxy_flag: 0.1,
  risk_score_alone: 0.05,

  // negative / exonerating
  recurring_merchant_match: -0.25, // R7 disputed-but-legitimate
  cleared_precedent_match: -0.2,
  in_character_for_customer: -0.2,
  customer_confirms: -0.9, // R3

  // step-up auth outcomes
  step_up_failed: 0.2,
  step_up_not_completed: 0.05,
  step_up_passed: -0.2,
} as const;

export type EvidenceKey = keyof typeof EVIDENCE_WEIGHTS;

export const POSITIVE_KEYS = (Object.keys(EVIDENCE_WEIGHTS) as EvidenceKey[]).filter(
  (k) => EVIDENCE_WEIGHTS[k] > 0,
);
export const NEGATIVE_KEYS = (Object.keys(EVIDENCE_WEIGHTS) as EvidenceKey[]).filter(
  (k) => EVIDENCE_WEIGHTS[k] < 0,
);

// --- ledger.py calibration constants, verbatim ----------------------------------------

export const BASELINE = -1.8;
export const SCALE = 4.1;

export function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-x));
}

export function computeProbability(evidenceKeys: readonly EvidenceKey[]): number {
  const total = evidenceKeys.reduce((sum, k) => sum + EVIDENCE_WEIGHTS[k], 0);
  const p = sigmoid(BASELINE + SCALE * total);
  return Math.min(1, Math.max(0, p));
}

// --- engine.py routing + thresholds, verbatim -------------------------------------------

import type { ActionName, ApprovalRoute } from "./types";

export type Route = ApprovalRoute;
export type Action = ActionName;

const AUTO_ACTIONS = new Set<Action>([
  "ALLOW_TRANSACTION",
  "MONITOR_CARD",
  "MONITOR_CONNECTED_CARDS",
  "WARN_CUSTOMER",
  "VERIFY_WITH_CUSTOMER",
  "STEP_UP_AUTH",
  "GENERATE_REPORT",
  "CREATE_CASE",
  "ESCALATE_TO_ANALYST",
  "CLOSE_NO_FRAUD",
]);
const L1_FIXED_ACTIONS = new Set<Action>(["DECLINE_TRANSACTION"]);
const L2_FIXED_ACTIONS = new Set<Action>(["BLOCK_ALL_CARDS", "FILE_REPORT"]);

export const R1_BLOCK_GUARD = 0.7;
export const CASE_CREATION_THRESHOLD = 0.3;
export const STOP_HIGH = 0.85;
export const STOP_LOW = 0.15;

// resolve_route: BLOCK_CARD <=2500 -> L1, >2500 -> L2 (exact boundary at 2500).
export function resolveRoute(action: Action, exposureUsd: number): Route {
  if (action === "BLOCK_CARD") return exposureUsd <= 2500 ? "L1" : "L2";
  if (AUTO_ACTIONS.has(action)) return "auto";
  if (L1_FIXED_ACTIONS.has(action)) return "L1";
  if (L2_FIXED_ACTIONS.has(action)) return "L2";
  throw new Error(`unknown action identifier: ${action}`);
}

// --- R1-R10 case state, mirroring engine.py's CaseState -------------------------------

export interface CaseState {
  fraudProbability: number;
  verdict: "fraud" | "legitimate" | "uncertain";
  exposureUsd: number;
  singleSignal: boolean;

  customerValidationRequested: boolean;
  customerResponse: "deny" | "confirm" | "no_reply" | null;
  noReplyWithin24h: boolean;

  cardTestingDetected: boolean;
  purchaseOver100AlreadyCleared: boolean;
  sharedDeviceProfile: boolean;
  sharedBillingRegion: boolean;
  sharedRecipientEmail: boolean;
  otherCardFraud: boolean;
  disputedMatchesRecurringPattern: boolean;
  evidenceConflicts: boolean;
  fitsNoKnownPattern: boolean;
  coordinatedOrRepeatedAbuseAcrossCustomers: boolean;

  blockAllCardsProposed: boolean;
  twoPlusCardsConfirmedFraud: boolean;
  credentialsConfirmedCompromised: boolean;
}

export interface FiredAction {
  action: Action;
  reasonRules: string[];
}

function ruleR1(s: CaseState): Action[] {
  if (s.singleSignal && s.fraudProbability < 0.7) return ["VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH"];
  return [];
}

function ruleR2(s: CaseState): Action[] {
  if (s.customerValidationRequested && s.customerResponse === "deny") {
    const actions: Action[] = ["BLOCK_CARD", "CREATE_CASE"];
    if (s.exposureUsd > 1000 || s.sharedDeviceProfile || s.otherCardFraud) actions.push("FILE_REPORT");
    return actions;
  }
  return [];
}

function ruleR3(s: CaseState): Action[] {
  return s.customerResponse === "confirm" ? ["CLOSE_NO_FRAUD"] : [];
}

function ruleR4(s: CaseState): Action[] {
  if (s.noReplyWithin24h) {
    const actions: Action[] = ["MONITOR_CARD", "DECLINE_TRANSACTION"];
    if (s.exposureUsd > 500) actions.push("ESCALATE_TO_ANALYST");
    return actions;
  }
  return [];
}

function ruleR5(s: CaseState): Action[] {
  if (!s.cardTestingDetected) return [];
  if (s.purchaseOver100AlreadyCleared) return ["BLOCK_CARD"];
  return ["DECLINE_TRANSACTION", "STEP_UP_AUTH"];
}

function ruleR6(s: CaseState): Action[] {
  if (s.sharedDeviceProfile || s.sharedBillingRegion || s.sharedRecipientEmail) {
    return ["CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS"];
  }
  return [];
}

function ruleR7(s: CaseState): Action[] {
  if (s.disputedMatchesRecurringPattern) return ["CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"];
  return [];
}

function ruleR7ForbiddenActions(s: CaseState): Set<Action> {
  if (s.disputedMatchesRecurringPattern) {
    return new Set<Action>(["BLOCK_CARD", "DECLINE_TRANSACTION", "FILE_REPORT"]);
  }
  return new Set();
}

function ruleR8(s: CaseState): Action[] {
  if ((s.verdict === "uncertain" && s.exposureUsd > 500) || s.evidenceConflicts) {
    return ["ESCALATE_TO_ANALYST"];
  }
  return [];
}

function ruleR9(s: CaseState): Action[] {
  if (s.fitsNoKnownPattern && s.coordinatedOrRepeatedAbuseAcrossCustomers) {
    return ["CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST"];
  }
  return [];
}

function ruleR10GuardOk(s: CaseState): boolean {
  return s.twoPlusCardsConfirmedFraud || s.credentialsConfirmedCompromised;
}

function applyR10(actions: Action[], s: CaseState): Action[] {
  if (!actions.includes("BLOCK_ALL_CARDS") && !s.blockAllCardsProposed) return actions;
  if (ruleR10GuardOk(s)) return actions;
  const downgraded = actions.map((a) => (a === "BLOCK_ALL_CARDS" ? "BLOCK_CARD" : a)) as Action[];
  if (s.blockAllCardsProposed && !actions.includes("BLOCK_ALL_CARDS") && !downgraded.includes("BLOCK_CARD")) {
    downgraded.push("BLOCK_CARD");
  }
  return downgraded;
}

const RULES: [string, (s: CaseState) => Action[]][] = [
  ["R1", ruleR1],
  ["R2", ruleR2],
  ["R3", ruleR3],
  ["R4", ruleR4],
  ["R5", ruleR5],
  ["R6", ruleR6],
  ["R7", ruleR7],
  ["R8", ruleR8],
  ["R9", ruleR9],
];

// apply_rules: run R1-R9 in order, dedupe/forbid/guard, terminal fallback if empty.
export function applyRules(s: CaseState): FiredAction[] {
  const forbidden = ruleR7ForbiddenActions(s);
  const orderedActions: Action[] = [];
  const reasons: Record<string, string[]> = {};

  for (const [ruleId, fn] of RULES) {
    for (const action of fn(s)) {
      if (forbidden.has(action)) continue;
      if (!orderedActions.includes(action)) {
        orderedActions.push(action);
        reasons[action] = [];
      }
      reasons[action].push(ruleId);
    }
  }

  let finalActions = applyR10(orderedActions, s);
  if (finalActions.includes("BLOCK_CARD") && !("BLOCK_ALL_CARDS" in reasons)) {
    reasons["BLOCK_CARD"] = [...(reasons["BLOCK_CARD"] ?? []), "R10"];
  }

  if (finalActions.length === 0) {
    if (s.fraudProbability <= STOP_LOW) {
      finalActions = ["CLOSE_NO_FRAUD"];
      reasons["CLOSE_NO_FRAUD"] = ["R3"];
    } else if (s.fraudProbability < CASE_CREATION_THRESHOLD) {
      finalActions = ["MONITOR_CARD"];
      reasons["MONITOR_CARD"] = ["R4"];
    } else {
      finalActions = ["CREATE_CASE", "MONITOR_CARD"];
      reasons["CREATE_CASE"] = ["R8"];
      reasons["MONITOR_CARD"] = ["R4"];
    }
  }

  return finalActions.map((a) => ({ action: a, reasonRules: reasons[a] ?? [] }));
}

// --- self-check: mirrors ledger.py demo() + engine.py demo() anchor cases -------------

export function selfCheck(): void {
  const fail = (msg: string): never => {
    throw new Error(`policySim selfCheck failed: ${msg}`);
  };

  // ledger.py demo(): no evidence reads low, not a coin flip.
  if (computeProbability([]) > 0.15) fail("no evidence must be <= 0.15");

  // README worked example (HHG-017): card_testing + shared_device + customer_denies ~= 0.89
  const pStrong = computeProbability(["card_testing_sequence", "shared_device_across_cards", "customer_denies"]);
  if (Math.abs(pStrong - 0.89) > 0.02) fail(`card_testing+shared_device+customer_denies expected ~0.89, got ${pStrong}`);

  // card_testing_sequence alone must stay under the R1 0.70 block line: 0.40-0.70 band.
  const pCardTestingAlone = computeProbability(["card_testing_sequence"]);
  if (!(pCardTestingAlone >= 0.4 && pCardTestingAlone <= 0.7)) {
    fail(`card_testing_sequence alone expected in [0.40,0.70], got ${pCardTestingAlone}`);
  }

  // risk_score_alone + customer_confirms -> R3 closes as legitimate, p <= 0.10
  const pConfirmed = computeProbability(["risk_score_alone", "customer_confirms"]);
  if (pConfirmed > 0.1) fail(`risk_score_alone+customer_confirms expected <=0.10, got ${pConfirmed}`);

  // risk_score_alone + recurring_merchant_match + in_character_for_customer -> R7 band, p <= 0.20
  const pR7 = computeProbability(["risk_score_alone", "recurring_merchant_match", "in_character_for_customer"]);
  if (pR7 > 0.2) fail(`R7 disputed-but-legitimate band expected <=0.20, got ${pR7}`);

  // BLOCK_CARD route boundary: exactly at 2500 is L1, 2500.01 is L2.
  if (resolveRoute("BLOCK_CARD", 2500) !== "L1") fail("BLOCK_CARD at 2500 must be L1");
  if (resolveRoute("BLOCK_CARD", 2500.01) !== "L2") fail("BLOCK_CARD at 2500.01 must be L2");
  if (resolveRoute("FILE_REPORT", 0) !== "L2") fail("FILE_REPORT must always be L2");
  if (resolveRoute("CREATE_CASE", 0) !== "auto") fail("CREATE_CASE must be auto");

  // R1: single weak signal -> verify + step-up, not a block.
  const r1 = applyRules(baseCaseState({ singleSignal: true, fraudProbability: 0.45 }));
  if (!(r1.some((a) => a.action === "VERIFY_WITH_CUSTOMER") && r1.some((a) => a.action === "STEP_UP_AUTH"))) {
    fail("R1 must fire VERIFY_WITH_CUSTOMER + STEP_UP_AUTH on single weak signal");
  }

  // R2: customer denies, exposure > 1000 -> FILE_REPORT added.
  const r2 = applyRules(
    baseCaseState({
      customerValidationRequested: true,
      customerResponse: "deny",
      exposureUsd: 1500,
    }),
  );
  if (!r2.some((a) => a.action === "FILE_REPORT")) fail("R2 must add FILE_REPORT above $1000 exposure");

  // R2 at exactly 1000 must NOT add FILE_REPORT ($1000 vs $1001 boundary, ">" not ">=").
  const r2Boundary = applyRules(
    baseCaseState({
      customerValidationRequested: true,
      customerResponse: "deny",
      exposureUsd: 1000,
    }),
  );
  if (r2Boundary.some((a) => a.action === "FILE_REPORT")) fail("R2 must NOT add FILE_REPORT at exactly $1000 (boundary is >1000)");

  // R7 trap: disputed recurring charge must never produce BLOCK_CARD or DECLINE_TRANSACTION,
  // even when R5's card-testing override would otherwise fire BLOCK_CARD.
  const r7 = applyRules(
    baseCaseState({
      disputedMatchesRecurringPattern: true,
      cardTestingDetected: true,
      purchaseOver100AlreadyCleared: true,
    }),
  );
  const r7Actions = r7.map((a) => a.action);
  if (r7Actions.includes("BLOCK_CARD")) fail("R7 must forbid BLOCK_CARD even if R5 also fired");
  if (r7Actions.includes("DECLINE_TRANSACTION")) fail("R7 must forbid DECLINE_TRANSACTION");

  // R10: BLOCK_ALL_CARDS downgrades to BLOCK_CARD when guard fails.
  const r10 = applyRules(
    baseCaseState({
      blockAllCardsProposed: true,
      twoPlusCardsConfirmedFraud: false,
      credentialsConfirmedCompromised: false,
    }),
  );
  if (!(r10.length === 1 && r10[0].action === "BLOCK_CARD")) fail("R10 must downgrade BLOCK_ALL_CARDS to BLOCK_CARD when guard fails");
}

function baseCaseState(overrides: Partial<CaseState>): CaseState {
  return {
    fraudProbability: 0,
    verdict: "uncertain",
    exposureUsd: 0,
    singleSignal: false,
    customerValidationRequested: false,
    customerResponse: null,
    noReplyWithin24h: false,
    cardTestingDetected: false,
    purchaseOver100AlreadyCleared: false,
    sharedDeviceProfile: false,
    sharedBillingRegion: false,
    sharedRecipientEmail: false,
    otherCardFraud: false,
    disputedMatchesRecurringPattern: false,
    evidenceConflicts: false,
    fitsNoKnownPattern: false,
    coordinatedOrRepeatedAbuseAcrossCustomers: false,
    blockAllCardsProposed: false,
    twoPlusCardsConfirmedFraud: false,
    credentialsConfirmedCompromised: false,
    ...overrides,
  };
}

export { baseCaseState };

// --- preset scenarios for the sandbox UI ------------------------------------------------

export interface Preset {
  id: string;
  label: string;
  description: string;
  evidenceKeys: EvidenceKey[];
  exposureUsd: number;
  caseOverrides: Partial<CaseState>;
}

export const PRESETS: Preset[] = [
  {
    id: "card_testing",
    label: "Card testing sequence",
    description: "3+ sub-$5 auths in under an hour, then a cleared $100+ purchase — R5's override fires BLOCK_CARD.",
    evidenceKeys: ["card_testing_sequence", "new_device_marker"],
    exposureUsd: 1800,
    caseOverrides: { cardTestingDetected: true, purchaseOver100AlreadyCleared: true, verdict: "fraud" },
  },
  {
    id: "recurring_disputed",
    label: "Recurring charge disputed",
    description: "R7 trap: same merchant, same amount, monthly — must NOT block despite the dispute.",
    evidenceKeys: ["recurring_merchant_match", "in_character_for_customer", "risk_score_alone"],
    exposureUsd: 45,
    caseOverrides: { disputedMatchesRecurringPattern: true, verdict: "legitimate" },
  },
  {
    id: "shared_device_ring",
    label: "Shared device ring",
    description: "Device profile shared across cards — R6 fires case creation, report, and connected-card monitoring.",
    evidenceKeys: ["shared_device_across_cards", "shared_region_cluster", "closed_case_match"],
    exposureUsd: 3200,
    caseOverrides: { sharedDeviceProfile: true, otherCardFraud: true, verdict: "fraud" },
  },
  {
    id: "single_weak_signal",
    label: "Single weak signal",
    description: "Risk score alone, nothing corroborating — R1 requires verification before any block.",
    evidenceKeys: ["risk_score_alone"],
    exposureUsd: 300,
    caseOverrides: { singleSignal: true, verdict: "uncertain" },
  },
];
