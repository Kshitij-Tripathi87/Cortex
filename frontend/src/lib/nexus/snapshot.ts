/**
 * Cortex Nexus — canonical graph-node → twin-Entity snapshot bridge.
 *
 * The persistent scenario simulator (POST /nexus/scenarios/{id}/simulate)
 * runs the deterministic twin against a caller-supplied entity snapshot;
 * the twin never reads a server-side singleton (v0.8.5-B3 contract). This
 * module builds that snapshot from the same workspace dependency graph the
 * operator sees, so every simulated KPI is traceable to persisted graph
 * records (spec invariant 2 — evidence over fabrication).
 *
 * Pure functions only: no I/O, deterministic outputs (spec invariant 5).
 */

export interface GraphNode {
  node_id?: string;
  entity_id?: string;
  entity_type?: string;
  attributes?: Record<string, unknown>;
  first_seen_version?: number;
  last_modified_version?: number;
}

/** Wire shape of the backend `Entity` model accepted by the simulate endpoint. */
export type TwinEntity = {
  entity_id: string;
  tenant_id: string;
  workspace_id: string;
  kind: string;
  natural_key: string;
  name: string;
  source: string;
  state: Record<string, unknown>;
};

export interface SnapshotBuildResult {
  entities: TwinEntity[];
  /** Nodes that could not be mapped, with the honest reason why. */
  excluded: Array<{ entity_id: string; reason: string }>;
}

/** EntityKind values accepted by the twin core (backend ontology). */
const TWIN_KINDS: ReadonlySet<string> = new Set([
  "organization", "workspace", "team", "user", "supplier", "manufacturer", "plant",
  "factory", "warehouse", "port", "product", "sku", "component", "material",
  "bill_of_materials", "purchase_order", "sales_order", "shipment", "route", "carrier",
  "inventory_position", "customer", "contract", "capacity", "demand", "forecast",
  "lead_time", "disruption", "signal", "scenario", "simulation", "decision",
  "recommendation", "execution", "outcome", "evidence", "agent", "tool", "policy",
  "approval",
]);

/** Common source-system aliases → canonical EntityKind values. */
const KIND_ALIASES: Readonly<Record<string, string>> = {
  vendor: "supplier",
  facility: "plant",
  factory: "factory",
  inventory: "inventory_position",
  inventory_item: "inventory_position",
  stock: "inventory_position",
  customer_order: "sales_order",
  salesorder: "sales_order",
  order: "sales_order",
  so: "sales_order",
  po: "purchase_order",
  purchaseorder: "purchase_order",
  bom: "bill_of_materials",
  warehouse: "warehouse",
  dc: "warehouse",
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Numeric keys the deterministic twin actually reads. Values arriving as
 * strings from source attributes are coerced so the twin sees numbers.
 */
const NUMERIC_STATE_KEYS: ReadonlySet<string> = new Set([
  "revenue", "sla_risk_pct", "on_hand_qty", "safety_stock_qty", "lead_time_days",
  "capacity_pct", "unit_price", "demand_multiplier", "availability_pct",
]);

const FNV_OFFSET = 0xcbf29ce484222325n;
const FNV_PRIME = 0x100000001b3n;

function fnv1a64(input: string, seed: bigint): bigint {
  let hash = seed;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= BigInt(input.charCodeAt(i));
    hash = (hash * FNV_PRIME) & 0xffffffffffffffffn;
  }
  return hash;
}

/**
 * Deterministic stand-in for UUID v5: two seeded FNV-1a passes fill the 128
 * bits. Only used when a graph node's entity_id is not already a UUID — the
 * mapping is stable for the life of the workspace and is never persisted
 * server-side (the twin matches mutations against this same function's
 * output within the same session).
 */
export function entityUuid(entityId: string): string {
  if (UUID_PATTERN.test(entityId)) return entityId.toLowerCase();
  const hi = fnv1a64(`${entityId}`, FNV_OFFSET);
  const lo = fnv1a64(`${entityId}#2`, FNV_PRIME);
  const bytes = new Uint8Array(16);
  for (let i = 0; i < 8; i += 1) {
    bytes[i] = Number((hi >> BigInt(56 - 8 * i)) & 0xffn);
    bytes[8 + i] = Number((lo >> BigInt(56 - 8 * i)) & 0xffn);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x80; // version nibble (custom)
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Map a graph entity_type to a twin EntityKind, or null when unmappable. */
export function twinKind(entityType: string | undefined): string | null {
  const normalized = (entityType ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!normalized) return null;
  if (TWIN_KINDS.has(normalized)) return normalized;
  return KIND_ALIASES[normalized] ?? null;
}

function coerceState(attributes: Record<string, unknown>): Record<string, unknown> {
  const state: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(attributes)) {
    if (NUMERIC_STATE_KEYS.has(key) && typeof value === "string") {
      const parsed = Number(value);
      state[key] = Number.isFinite(parsed) ? parsed : value;
    } else {
      state[key] = value;
    }
  }
  return state;
}

/**
 * Build the twin snapshot from workspace graph nodes. Nodes that cannot be
 * represented as twin entities are reported in `excluded` rather than
 * silently dropped — missing coverage is surfaced, never hidden (spec:
 * missing/stale data must be explicit).
 */
export function buildTwinSnapshot(
  nodes: GraphNode[],
  ids: { tenantId: string; workspaceId: string },
): SnapshotBuildResult {
  const entities: TwinEntity[] = [];
  const excluded: Array<{ entity_id: string; reason: string }> = [];
  const seen = new Set<string>();

  for (const node of nodes) {
    const entityId = node.entity_id ?? node.node_id ?? "";
    if (!entityId) {
      excluded.push({ entity_id: "(missing)", reason: "graph node has no entity identifier" });
      continue;
    }
    if (seen.has(entityId)) continue;
    seen.add(entityId);

    const kind = twinKind(node.entity_type);
    if (!kind) {
      excluded.push({ entity_id: entityId, reason: `entity_type "${node.entity_type ?? ""}" has no twin kind` });
      continue;
    }
    if (!UUID_PATTERN.test(ids.tenantId) || !UUID_PATTERN.test(ids.workspaceId)) {
      excluded.push({ entity_id: entityId, reason: "workspace or tenant id is not a UUID" });
      continue;
    }

    const attributes = node.attributes ?? {};
    entities.push({
      entity_id: entityUuid(entityId),
      tenant_id: ids.tenantId,
      workspace_id: ids.workspaceId,
      kind,
      natural_key: entityId,
      name: String(attributes.name ?? attributes.description ?? entityId),
      source: String(attributes.source ?? "workspace-graph"),
      state: coerceState(attributes),
    });
  }
  return { entities, excluded };
}

/** Highest persisted world-state version visible on the graph nodes. */
export function graphWorldStateVersion(nodes: GraphNode[]): number {
  return nodes.reduce(
    (max, node) => Math.max(max, node.last_modified_version ?? 0, node.first_seen_version ?? 0),
    0,
  );
}
