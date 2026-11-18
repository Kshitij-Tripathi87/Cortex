import { describe, expect, it } from "vitest";
import {
  attentionQueue,
  cockpitTiles,
  emptyQueueMessage,
  formatIsoDay,
  formatMoment,
  sourceLine,
  unlistedCount,
  workspaceState,
  type WorkspaceOverview,
} from "./overview";

// The site prints moments in the visitor's own time zone; pin one for the expected text.
process.env.TZ = "UTC";

/** A real answer of GET /nexus/workspace/overview, shortened to one item of each kind. */
const PUBLISHED: WorkspaceOverview = {
  as_of: "2026-11-17",
  published: { version: 5, published_at: "2026-11-17T09:05:24.240108+00:00", files: ["inventory.csv"] },
  records: {
    total: 27,
    by_type: [
      { entity_type: "PurchaseOrder", noun: "purchase orders", count: 7 },
      { entity_type: "InventoryItem", noun: "inventory records", count: 6 },
    ],
  },
  relationships: { total: 26 },
  reading: { complete: true, records_read: 27, records_total: 27 },
  summary: [
    "3 of 7 purchase orders are late or flagged: PO-5001, PO-5002 and PO-5006.",
    "3 of 6 stock positions are below threshold: C-2004 at WH-PUNE (1,500 on hand, safety stock 2,000).",
    "2 suppliers or partners are flagged by their own status: S-101 Bharat Castings Pvt Ltd (delayed).",
  ],
  late: {
    count: 3,
    checked: 7,
    items: [
      {
        entity_type: "PurchaseOrder",
        entity_id: "PO-5001",
        noun: "purchase order",
        days_late: 21,
        status: "delayed",
        promised_date: "2026-11-05",
        expected_date: "2026-11-26",
        subject: "400 x C-2000 Cast Iron Housing from S-101 Bharat Castings Pvt Ltd",
        reasons: "status is delayed; now expected 2026-11-26, 21 days after the promised 2026-11-05",
        text: "PO-5001: 400 x C-2000 Cast Iron Housing from S-101 Bharat Castings Pvt Ltd; status is delayed; now expected 2026-11-26, 21 days after the promised 2026-11-05.",
      },
    ],
  },
  stock: {
    count: 3,
    checked: 6,
    items: [
      {
        entity_type: "InventoryItem",
        entity_id: "INV-1",
        product: { entity_type: "Product", entity_id: "C-2000", name: "Cast Iron Housing" },
        facility: { entity_type: "Facility", entity_id: "WH-PUNE", name: "Pune Plant Store" },
        on_hand: 120,
        threshold: 300,
        threshold_field: "safety_stock",
        out_of_stock: false,
        where: "C-2000 Cast Iron Housing at WH-PUNE Pune Plant Store",
        detail: "120 on hand against a safety stock of 300 (180 short)",
        text: "C-2000 Cast Iron Housing at WH-PUNE Pune Plant Store: 120 on hand against a safety stock of 300 (180 short).",
      },
    ],
  },
  flagged: {
    count: 2,
    items: [
      {
        entity_type: "Supplier",
        entity_id: "S-101",
        name: "Bharat Castings Pvt Ltd",
        noun: "supplier",
        status: "delayed",
        text: "S-101 Bharat Castings Pvt Ltd: status is delayed.",
      },
    ],
  },
  attention_count: 8,
};

const NOTHING_PUBLISHED: WorkspaceOverview = {
  as_of: "2026-11-17",
  published: null,
  records: { total: 0, by_type: [] },
  relationships: { total: 0 },
  reading: { complete: true, records_read: 0, records_total: 0 },
  summary: [],
  late: { count: 0, checked: 0, items: [] },
  stock: { count: 0, checked: 0, items: [] },
  flagged: { count: 0, items: [] },
  attention_count: 0,
};

/** Only suppliers were published: no orders and no stock to check. */
const SUPPLIERS_ONLY: WorkspaceOverview = {
  ...NOTHING_PUBLISHED,
  published: { version: 1, published_at: "2026-11-17T09:00:00+00:00", files: ["suppliers.csv"] },
  records: { total: 6, by_type: [{ entity_type: "Supplier", noun: "suppliers", count: 6 }] },
  reading: { complete: true, records_read: 6, records_total: 6 },
  summary: [
    "No orders or shipments are published, so lateness cannot be judged.",
    "No inventory with a readable quantity is published, so stock cannot be judged.",
  ],
};

describe("cockpitTiles", () => {
  it("shows the server's counts and how many records each was judged on", () => {
    expect(cockpitTiles(PUBLISHED, [])).toEqual([
      { label: "Late orders", value: "3", detail: "of 7 orders and shipments checked" },
      { label: "Stock below threshold", value: "3", detail: "of 6 stock records checked" },
      {
        label: "Flagged partners",
        value: "2",
        detail: "Suppliers, carriers or customers whose own status marks a problem",
      },
      {
        label: "Recorded risks",
        value: "0",
        detail: "Risk records come from the API, not from uploads",
      },
    ]);
  });

  it("shows a dash, not a zero, for what could not be checked", () => {
    const [late, stock, flagged] = cockpitTiles(SUPPLIERS_ONLY, []);
    expect(late).toEqual({ label: "Late orders", value: "—", detail: "No orders or shipments in your data" });
    expect(stock).toEqual({ label: "Stock below threshold", value: "—", detail: "No stock records in your data" });
    // Suppliers were published and none is flagged: that zero is a finding.
    expect(flagged.value).toBe("0");
  });

  it("says that nothing is published instead of reporting zeros", () => {
    const tiles = cockpitTiles(NOTHING_PUBLISHED, []);
    expect(tiles.slice(0, 3).map((tile) => tile.value)).toEqual(["—", "—", "—"]);
    expect(tiles.slice(0, 3).map((tile) => tile.detail)).toEqual([
      "No data published yet",
      "No data published yet",
      "No data published yet",
    ]);
  });

  it("counts the recorded risks by severity", () => {
    const risks = [{ severity: "CRITICAL" }, { severity: "HIGH" }, { severity: "HIGH" }, { severity: "LOW" }];
    expect(cockpitTiles(PUBLISHED, risks)[3]).toEqual({
      label: "Recorded risks",
      value: "4",
      detail: "1 critical · 2 high",
    });
  });

  it("does not show a figure while the data is still being read", () => {
    const tiles = cockpitTiles(null, []);
    expect(tiles.slice(0, 3).map((tile) => tile.value)).toEqual(["—", "—", "—"]);
    expect(tiles[0].detail).toBe("Reading your data…");
  });

  it("says so when the data could not be read, instead of waiting forever", () => {
    const tiles = cockpitTiles(null, [], "failed");
    expect(tiles.slice(0, 3).map((tile) => tile.value)).toEqual(["—", "—", "—"]);
    expect(tiles.slice(0, 3).map((tile) => tile.detail)).toEqual([
      "Could not be read",
      "Could not be read",
      "Could not be read",
    ]);
  });
});

describe("workspaceState", () => {
  it("shows the published version and the totals", () => {
    expect(workspaceState(PUBLISHED)).toEqual([
      { label: "Published data", value: "Version 5" },
      { label: "Last published", value: "17 Nov 2026, 09:05" },
      { label: "Records", value: "27" },
      { label: "Relationships", value: "26" },
    ]);
  });

  it("says when nothing is published", () => {
    expect(workspaceState(NOTHING_PUBLISHED)).toEqual([
      { label: "Published data", value: "Nothing published" },
      { label: "Records", value: "0" },
      { label: "Relationships", value: "0" },
    ]);
  });

  it("groups large totals", () => {
    const big = { ...PUBLISHED, records: { total: 12345, by_type: [] }, relationships: { total: 1234567 } };
    const rows = workspaceState(big);
    expect(rows[2].value).toBe("12,345");
    expect(rows[3].value).toBe("1,234,567");
  });
});

describe("attentionQueue", () => {
  it("lists late orders, then low stock, then flagged partners", () => {
    expect(attentionQueue(PUBLISHED)).toEqual([
      {
        key: "late:PurchaseOrder:PO-5001",
        kind: "late",
        badge: "21 days late",
        title: "Purchase order PO-5001",
        lines: [
          "400 x C-2000 Cast Iron Housing from S-101 Bharat Castings Pvt Ltd",
          "Status is delayed; now expected 2026-11-26, 21 days after the promised 2026-11-05",
        ],
        question: "Tell me about PO-5001",
      },
      {
        key: "stock:InventoryItem:INV-1",
        kind: "stock",
        badge: "Low stock",
        title: "C-2000 Cast Iron Housing at WH-PUNE Pune Plant Store",
        lines: ["120 on hand against a safety stock of 300 (180 short)"],
        question: "Tell me about C-2000",
      },
      {
        key: "flagged:Supplier:S-101",
        kind: "flagged",
        badge: "Flagged",
        title: "S-101 Bharat Castings Pvt Ltd",
        lines: ["Supplier with status delayed"],
        question: "Tell me about S-101",
      },
    ]);
  });

  it("labels an order that is only flagged by its status, and an empty shelf", () => {
    const overview: WorkspaceOverview = {
      ...PUBLISHED,
      late: {
        count: 2,
        checked: 2,
        items: [
          { ...PUBLISHED.late.items[0], entity_id: "PO-1", days_late: null, subject: "", reasons: "status is delayed" },
          { ...PUBLISHED.late.items[0], entity_id: "PO-2", days_late: 1 },
        ],
      },
      stock: {
        count: 1,
        checked: 1,
        items: [{ ...PUBLISHED.stock.items[0], product: null, out_of_stock: true, where: "INV-9", detail: "0 on hand" }],
      },
    };
    const [flaggedOrder, oneDay, shelf] = attentionQueue(overview);
    expect(flaggedOrder.badge).toBe("Flagged");
    // No empty first line when the record names no product or partner.
    expect(flaggedOrder.lines).toEqual(["Status is delayed"]);
    expect(oneDay.badge).toBe("1 day late");
    expect(shelf.badge).toBe("Out of stock");
    // Without a product the question names the stock record itself.
    expect(shelf.question).toBe("Tell me about INV-1");
  });

  it("is empty without data", () => {
    expect(attentionQueue(null)).toEqual([]);
    expect(attentionQueue(NOTHING_PUBLISHED)).toEqual([]);
  });
});

describe("unlistedCount", () => {
  it("is the number of findings the list leaves out", () => {
    // 8 findings, one of each kind listed here.
    expect(unlistedCount(PUBLISHED)).toBe(5);
    expect(unlistedCount(NOTHING_PUBLISHED)).toBe(0);
    expect(unlistedCount(null)).toBe(0);
  });
});

describe("emptyQueueMessage", () => {
  it("explains what to do when nothing is published", () => {
    const message = emptyQueueMessage(NOTHING_PUBLISHED);
    expect(message.title).toBe("Nothing to check yet");
    expect(message.detail).toContain("Upload a file, review it and publish it.");
  });

  it("repeats the server's sentences, which say what could not be judged", () => {
    expect(emptyQueueMessage(SUPPLIERS_ONLY)).toEqual({
      title: "Nothing stands out",
      detail:
        "No orders or shipments are published, so lateness cannot be judged. No inventory with a readable quantity is published, so stock cannot be judged.",
    });
  });

  it("says it is still reading before the answer arrives", () => {
    expect(emptyQueueMessage(null).title).toBe("Reading your published data…");
  });

  it("says so when the read failed", () => {
    expect(emptyQueueMessage(null, "failed")).toEqual({
      title: "Your data could not be read",
      detail: "Use Retry at the top of the page.",
    });
  });
});

describe("sourceLine", () => {
  it("names the version and the day lateness was judged on", () => {
    expect(sourceLine(PUBLISHED)).toBe(
      "Read from your published data, version 5 · lateness judged on 17 Nov 2026 (UTC).",
    );
  });

  it("says when only part of the records was read", () => {
    const partial = { ...PUBLISHED, reading: { complete: false, records_read: 12000, records_total: 30500 } };
    expect(sourceLine(partial)).toBe(
      "Read from your published data, version 5 · lateness judged on 17 Nov 2026 (UTC) · only 12,000 of 30,500 records were read, so the findings cover that part.",
    );
  });

  it("is absent when nothing is published", () => {
    expect(sourceLine(NOTHING_PUBLISHED)).toBeNull();
    expect(sourceLine(null)).toBeNull();
  });
});

describe("dates", () => {
  it("prints an ISO day as the calendar day it names, whatever the time zone", () => {
    expect(formatIsoDay("2026-11-17")).toBe("17 Nov 2026");
    expect(formatIsoDay("2026-03-04")).toBe("4 Mar 2026");
    expect(formatIsoDay("not a date")).toBe("not a date");
  });

  it("prints a moment with its time", () => {
    expect(formatMoment("2026-11-17T09:05:24.240108+00:00")).toBe("17 Nov 2026, 09:05");
    expect(formatMoment(null)).toBeNull();
    expect(formatMoment("nonsense")).toBeNull();
  });
});
