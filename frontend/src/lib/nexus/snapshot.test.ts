import { describe, expect, it } from "vitest";

import {
  buildTwinSnapshot,
  entityUuid,
  graphWorldStateVersion,
  twinKind,
  type GraphNode,
} from "./snapshot";

const IDS = { tenantId: "11111111-1111-4111-8111-111111111111", workspaceId: "22222222-2222-4222-8222-222222222222" };

function node(overrides: Partial<GraphNode>): GraphNode {
  return { entity_id: "e1", entity_type: "supplier", attributes: {}, ...overrides };
}

describe("entityUuid", () => {
  it("passes UUID-shaped identifiers through unchanged (case-normalized)", () => {
    expect(entityUuid("ABCDEF01-2345-6789-ABCD-EF0123456789")).toBe(
      "abcdef01-2345-6789-abcd-ef0123456789",
    );
  });

  it("derives a stable UUID for arbitrary source keys", () => {
    const first = entityUuid("SAP-VENDOR-42");
    const second = entityUuid("SAP-VENDOR-42");
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    expect(second).toBe(first);
    expect(entityUuid("SAP-VENDOR-43")).not.toBe(first);
  });
});

describe("twinKind", () => {
  it("maps aliases to canonical EntityKind values", () => {
    expect(twinKind("Facility")).toBe("plant");
    expect(twinKind("customer_order")).toBe("sales_order");
    expect(twinKind("Inventory")).toBe("inventory_position");
  });

  it("passes canonical kinds through and rejects unknowns", () => {
    expect(twinKind("supplier")).toBe("supplier");
    expect(twinKind("spacecraft")).toBeNull();
    expect(twinKind(undefined)).toBeNull();
  });
});

describe("buildTwinSnapshot", () => {
  it("maps graph nodes into wire-compatible twin entities", () => {
    const { entities, excluded } = buildTwinSnapshot(
      [
        node({
          entity_id: "sup-1",
          entity_type: "supplier",
          attributes: { name: "Acme", lead_time_days: "9", capacity_pct: 100 },
        }),
      ],
      IDS,
    );
    expect(excluded).toHaveLength(0);
    expect(entities).toHaveLength(1);
    const entity = entities[0];
    expect(entity.entity_id).toBe(entityUuid("sup-1"));
    expect(entity.kind).toBe("supplier");
    expect(entity.natural_key).toBe("sup-1");
    expect(entity.name).toBe("Acme");
    expect(entity.state.lead_time_days).toBe(9);
    expect(entity.state.capacity_pct).toBe(100);
  });

  it("excludes unmappable nodes with an explicit reason instead of dropping silently", () => {
    const { entities, excluded } = buildTwinSnapshot(
      [node({ entity_id: "x1", entity_type: "spacecraft" }), node({ entity_id: "" })],
      IDS,
    );
    expect(entities).toHaveLength(0);
    expect(excluded).toHaveLength(2);
    expect(excluded[0].reason).toContain("spacecraft");
    expect(excluded[1].reason).toContain("no entity identifier");
  });

  it("deduplicates repeated entity ids and is deterministic", () => {
    const nodes = [node({ entity_id: "dup" }), node({ entity_id: "dup" })];
    const a = buildTwinSnapshot(nodes, IDS);
    const b = buildTwinSnapshot(nodes, IDS);
    expect(a.entities).toHaveLength(1);
    expect(a).toEqual(b);
  });
});

describe("graphWorldStateVersion", () => {
  it("returns the highest version marker across nodes", () => {
    expect(
      graphWorldStateVersion([
        node({ last_modified_version: 4 }),
        node({ first_seen_version: 7 }),
        node({}),
      ]),
    ).toBe(7);
    expect(graphWorldStateVersion([])).toBe(0);
  });
});
