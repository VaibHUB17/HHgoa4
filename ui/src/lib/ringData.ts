import type { CaseAnswer } from "./types";

// Derives the device-ring structure for the interactive explorer from a single case's
// own fields — no invented entities. HHG-014's shape:
//   - `case.connected_card_ids`: the cards sharing the flagged device (17 on HHG-014)
//   - `case.connected_device_profiles`: the shared handset(s) (usually exactly one)
//   - `sar.subjects`: includes the flagged card id (e.g. "C13487-K1"), which is NOT
//     itself in connected_card_ids — it is the card under investigation, distinct from
//     the ring it connects to. We recover it from sar.subjects (first id containing "-"
//     that isn't already in connected_card_ids); if absent, we degrade to labelling the
//     first connected card as the anchor rather than inventing an id.

export type RingNodeKind = "flagged-card" | "device" | "ring-card";

export interface RingNode {
  id: string;
  kind: RingNodeKind;
  label: string;
  /** Hops from the flagged card, by construction: 0 = flagged card, 1 = device, 2 = ring card. */
  hops: number;
}

export interface RingEdge {
  from: string;
  to: string;
}

export interface RingGraph {
  nodes: RingNode[];
  edges: RingEdge[];
  flaggedCardId: string | null;
  deviceId: string | null;
}

function shortDeviceLabel(device: string): string {
  return device.split("|")[0]?.trim() || device;
}

export function buildRingGraph(c: CaseAnswer): RingGraph {
  const ringCardIds = c.case.connected_card_ids ?? [];
  const devices = c.case.connected_device_profiles ?? [];
  const deviceId = devices[0] ?? null;

  const ringCardSet = new Set(ringCardIds);
  const flaggedCardId =
    c.sar?.subjects?.find((s) => s.includes("-") && !ringCardSet.has(s)) ??
    ringCardIds[0] ??
    null;

  const nodes: RingNode[] = [];
  const edges: RingEdge[] = [];

  if (flaggedCardId) {
    nodes.push({ id: flaggedCardId, kind: "flagged-card", label: flaggedCardId, hops: 0 });
  }

  if (deviceId) {
    nodes.push({ id: deviceId, kind: "device", label: shortDeviceLabel(deviceId), hops: 1 });
    if (flaggedCardId) edges.push({ from: flaggedCardId, to: deviceId });
  }

  for (const cardId of ringCardIds) {
    if (cardId === flaggedCardId) continue; // degrade gracefully, never duplicate a node
    nodes.push({ id: cardId, kind: "ring-card", label: cardId, hops: deviceId ? 2 : 1 });
    if (deviceId) edges.push({ from: cardId, to: deviceId });
    else if (flaggedCardId) edges.push({ from: cardId, to: flaggedCardId });
  }

  return { nodes, edges, flaggedCardId, deviceId };
}
