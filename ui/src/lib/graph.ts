import type { CaseAnswer, CaseGraph, GraphNode, GraphEdge } from "./types";

// Derives an entity neighborhood from a single case's own fields (card id parsed for
// customer_id, affected/flagged transactions, connected cards, connected device profiles).
// Not a live graph query — the case JSON already carries every ID this view needs, and the
// README's suggested schema (Customer/Card/Transaction/DeviceProfile/BillingRegion) gives
// the vertex kinds. Deterministic so the same case always lays out the same way.

function customerIdFromCardId(cardId: string): string {
  // card ids look like "C04570-K1" -> customer "C04570"
  const idx = cardId.indexOf("-");
  return idx === -1 ? cardId : cardId.slice(0, idx);
}

export function buildCaseGraph(c: CaseAnswer, primaryCardId: string): CaseGraph {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];

  const addNode = (n: GraphNode) => {
    if (!nodes.has(n.id)) nodes.set(n.id, n);
  };
  const addEdge = (from: string, to: string, label?: string) => {
    edges.push({ from, to, label });
  };

  const customerId = customerIdFromCardId(primaryCardId);
  addNode({ id: customerId, kind: "Customer", label: customerId });

  addNode({ id: primaryCardId, kind: "Card", label: primaryCardId, fraud: c.case.verdict === "fraud" });
  addEdge(customerId, primaryCardId, "OWNS");

  for (const txnId of c.case.affected_txn_ids) {
    addNode({
      id: txnId,
      kind: "Transaction",
      label: txnId,
      flagged: txnId === c.case.first_suspicious_txn_id,
      fraud: c.case.verdict === "fraud",
    });
    addEdge(primaryCardId, txnId, "MADE");
  }

  // Connected cards — the ring-detection story. Each connected card belongs to its own
  // customer (unknown here, so labeled by card) and shares the device profile node(s).
  for (const cardId of c.case.connected_card_ids) {
    const custId = customerIdFromCardId(cardId);
    addNode({ id: custId, kind: "Customer", label: custId });
    addNode({ id: cardId, kind: "Card", label: cardId });
    addEdge(custId, cardId, "OWNS");
  }

  // Device profiles — the shared element across cards.
  for (const device of c.case.connected_device_profiles) {
    const shortLabel = device.split("|")[0]?.trim() || device;
    addNode({ id: device, kind: "DeviceProfile", label: shortLabel });
    addEdge(primaryCardId, device, "FROM_DEVICE");
    for (const cardId of c.case.connected_card_ids) {
      addEdge(cardId, device, "FROM_DEVICE");
    }
  }

  return { nodes: Array.from(nodes.values()), edges };
}
