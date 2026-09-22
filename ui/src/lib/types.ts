// Types mirror README.md's "Answer Format" section exactly (field names, enums, shapes).
// Source: cases/<case_id>.json — one file per case, produced by the agent.

export type Verdict = "fraud" | "legitimate" | "uncertain";

export type CaseStatus = "open" | "closed_fraud" | "closed_legitimate" | "escalated";

export type Pattern =
  | "card_testing"
  | "card_not_present_fraud"
  | "card_not_present_new_device"
  | "out_of_region_use"
  | "account_takeover"
  | "undocumented"
  | "none";

export type EvidenceSource = "graph" | "document" | "customer" | "external";

export type ActionName =
  | "ALLOW_TRANSACTION"
  | "DECLINE_TRANSACTION"
  | "MONITOR_CARD"
  | "MONITOR_CONNECTED_CARDS"
  | "WARN_CUSTOMER"
  | "VERIFY_WITH_CUSTOMER"
  | "STEP_UP_AUTH"
  | "BLOCK_CARD"
  | "BLOCK_ALL_CARDS"
  | "GENERATE_REPORT"
  | "CREATE_CASE"
  | "FILE_REPORT"
  | "ESCALATE_TO_ANALYST"
  | "CLOSE_NO_FRAUD";

export type ApprovalRoute = "auto" | "L1" | "L2";

export type EvidenceRequestType = "customer_validation" | "step_up_auth" | "analyst_info";

export interface EvidenceItem {
  claim: string;
  source: EvidenceSource;
  ref: string;
  entity_ids: string[];
}

export interface EvidenceRequest {
  type: EvidenceRequestType;
  asked_after_step: number;
  assumed_response: string;
}

export interface RecommendedAction {
  action: ActionName;
  route: ApprovalRoute;
  reason: string;
}

export interface NextBestActions {
  initial: RecommendedAction[];
  final: RecommendedAction[];
  what_changed: string;
}

export interface CaseRecord {
  status: CaseStatus;
  verdict: Verdict;
  fraud_probability: number;
  pattern: Pattern;
  pattern_description: string;
  affected_txn_ids: string[];
  first_suspicious_txn_id: string;
  connected_card_ids: string[];
  connected_device_profiles: string[];
  exposure_usd: number;
  evidence: EvidenceItem[];
  similar_prior_cases: string[];
  summary: string;
  written_to_graph: boolean;
  graph_case_id: string;
}

export interface SarRecord {
  file: boolean;
  reason: string;
  narrative: string;
  subjects: string[];
  total_amount_usd: number;
  activity_dates: [string, string] | [];
}

export interface CaseAnswer {
  case_id: string;
  case: CaseRecord;
  evidence_requests: EvidenceRequest[];
  next_best_actions: NextBestActions;
  sar: SarRecord;
  stop_reason: string;
  tool_calls: number;
  tokens: number;
  latency_s: number;
}

// --- Graph-neighborhood shape for the case detail graph view ---
// Not part of README's answer format; derived from case fields (card/device/txn ids)
// plus the suggested schema (Customer/Card/Transaction/DeviceProfile/BillingRegion)
// so the graph view can render a neighborhood for any case without new data plumbing.

export type GraphNodeKind =
  | "Customer"
  | "Card"
  | "Transaction"
  | "DeviceProfile"
  | "BillingRegion";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  flagged?: boolean;
  fraud?: boolean;
}

export interface GraphEdge {
  from: string;
  to: string;
  label?: string;
}

export interface CaseGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
