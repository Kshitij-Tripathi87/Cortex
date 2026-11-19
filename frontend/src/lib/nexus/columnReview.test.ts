import { describe, expect, it } from "vitest";
import {
  aKind,
  buildDecision,
  columnMeaning,
  decidable,
  decideAllLabel,
  decisionBlocker,
  decisionNotice,
  fileHeadline,
  fileStanding,
  fileTotals,
  kindIsSettled,
  kindLabel,
  type ColumnDecisionResult,
  type ReviewColumn,
  type ReviewFile,
} from "./columnReview";

function column(name: string, overrides: Partial<ReviewColumn> = {}): ReviewColumn {
  return {
    source_column: name,
    canonical_field: name,
    role: "value",
    links_to: null,
    examples: [],
    pending: 6,
    accepted: 0,
    rejected: 0,
    superseded: 0,
    in_conflict: 0,
    ...overrides,
  };
}

const SUPPLIERS: ReviewFile = {
  file_id: "file-1",
  name: "suppliers.csv",
  rows: 6,
  entity: "Supplier",
  entity_source: "columns",
  key_field: "supplier_id",
  key_column: "supplier_id",
  problem: null,
  columns: [
    column("supplier_id", { role: "key", examples: ["S-100", "S-101", "S-102"] }),
    column("supplier_name"),
    column("country"),
  ],
};

const ORDERS: ReviewFile = {
  file_id: "file-2",
  name: "purchase_orders.csv",
  rows: 3,
  entity: "PurchaseOrder",
  entity_source: "columns",
  key_field: "po_number",
  key_column: "po_number",
  problem: null,
  columns: [
    column("po_number", { role: "key", pending: 3 }),
    column("supplier_id", { role: "link", links_to: "Supplier", pending: 3 }),
    column("quantity", { pending: 3 }),
  ],
};

/** Column names no registry knows: nothing says what a row is. */
const UNKNOWN: ReviewFile = {
  file_id: "file-3",
  name: "lieferanten.csv",
  rows: 2,
  entity: null,
  entity_source: null,
  key_field: null,
  key_column: null,
  problem: null,
  columns: [
    column("Lieferant Nr", { canonical_field: "lieferant_nr", pending: 2 }),
    column("Firma", { canonical_field: "firma", pending: 2 }),
    column("Land", { canonical_field: "land", pending: 2 }),
  ],
};

const SUPPLIER_KIND = { entity: "Supplier", key_field: "supplier_id" };
const REASON = "Checked against the ERP export of 14 November.";

describe("the kind of record", () => {
  it("is named in ordinary words", () => {
    expect(kindLabel("Supplier")).toBe("supplier");
    expect(kindLabel("PurchaseOrder")).toBe("purchase order");
    expect(kindLabel("InventoryItem")).toBe("inventory item");
    expect(kindLabel("BOM")).toBe("bom");
    expect(aKind("Supplier")).toBe("a supplier");
    expect(aKind("PurchaseOrder")).toBe("a purchase order");
    expect(aKind("InventoryItem")).toBe("an inventory item");
    expect(aKind("Organization")).toBe("an organization");
  });

  it("is settled by the column names or by an accepted decision, not by a proposal", () => {
    expect(kindIsSettled(SUPPLIERS)).toBe(true);
    expect(kindIsSettled({ ...SUPPLIERS, entity_source: "review" })).toBe(true);
    expect(kindIsSettled({ ...SUPPLIERS, entity_source: "proposed" })).toBe(false);
    expect(kindIsSettled(UNKNOWN)).toBe(false);
  });
});

describe("what the page says about a file", () => {
  it("says what each row is and how that is known", () => {
    expect(fileHeadline(SUPPLIERS)).toBe(
      "Each row of suppliers.csv is a supplier, recognised from the column supplier_id.",
    );
    expect(fileHeadline({ ...UNKNOWN, entity: "Supplier", entity_source: "review", key_field: "supplier_id", key_column: "Lieferant Nr" })).toBe(
      "Each row of lieferanten.csv is a supplier, identified by the column Lieferant Nr.",
    );
    expect(fileHeadline(ORDERS)).toBe(
      "Each row of purchase_orders.csv is a purchase order, recognised from the column po_number.",
    );
  });

  it("says so when the column names do not tell", () => {
    const expected =
      "The column names of lieferanten.csv do not say what each row is. Choose what a row is, and the column that identifies each one.";
    expect(fileHeadline(UNKNOWN)).toBe(expected);
    // A kind that was only asked for is still the reviewer's to choose.
    expect(fileHeadline({ ...UNKNOWN, entity: "Supplier", entity_source: "proposed", key_field: "supplier_id" })).toBe(expected);
  });

  it("does not claim an identifying column that is not there", () => {
    expect(fileHeadline({ ...SUPPLIERS, entity_source: "review", key_column: null })).toBe(
      "Each row of suppliers.csv is a supplier, but no column holds the supplier_id that identifies each one.",
    );
  });

  it("says what each column is to the record", () => {
    expect(columnMeaning(SUPPLIERS.columns[0], SUPPLIERS)).toBe("identifies each supplier");
    expect(columnMeaning(SUPPLIERS.columns[1], SUPPLIERS)).toBe("a field of the supplier");
    expect(columnMeaning(ORDERS.columns[1], ORDERS)).toBe("links each purchase order to a supplier");
    expect(columnMeaning(UNKNOWN.columns[0], UNKNOWN)).toBe("");
  });
});

describe("where a file stands", () => {
  it("counts what one decision can decide", () => {
    expect(decidable(column("country", { pending: 6, in_conflict: 2 }))).toBe(4);
    expect(decidable(column("country", { pending: 0, accepted: 6 }))).toBe(0);
    // A count of conflicts that ran ahead of the values never goes below zero.
    expect(decidable(column("country", { pending: 1, in_conflict: 3 }))).toBe(0);
    expect(fileTotals(SUPPLIERS)).toEqual({
      pending: 18,
      accepted: 0,
      rejected: 0,
      superseded: 0,
      inConflict: 0,
      decidable: 18,
    });
  });

  it("says how many values wait", () => {
    expect(fileStanding(SUPPLIERS)).toBe("18 values wait for a decision.");
    expect(fileStanding({ ...SUPPLIERS, columns: [column("supplier_id", { pending: 1 })] })).toBe(
      "1 value waits for a decision.",
    );
  });

  it("says what was decided once nothing waits", () => {
    const decided: ReviewFile = {
      ...SUPPLIERS,
      columns: [
        column("supplier_id", { pending: 0, accepted: 2 }),
        column("supplier_name", { pending: 0, accepted: 2 }),
        column("country", { pending: 0, rejected: 2 }),
      ],
    };
    expect(fileStanding(decided)).toBe("Every value is decided: 4 values accepted, 2 values rejected.");
    expect(
      fileStanding({ ...SUPPLIERS, columns: [column("supplier_id", { pending: 0, accepted: 1, superseded: 1 })] }),
    ).toBe("Every value is decided: 1 value accepted, 1 value withdrawn.");
    expect(fileStanding({ ...SUPPLIERS, columns: [column("supplier_id", { pending: 0 })] })).toBe(
      "This file has no values to decide.",
    );
  });

  it("says which waiting values are left to a conflict, and what is already decided", () => {
    const mixed: ReviewFile = {
      ...SUPPLIERS,
      columns: [
        column("supplier_id", { pending: 0, accepted: 6 }),
        column("supplier_name", { pending: 6 }),
        column("country", { pending: 6, in_conflict: 2 }),
      ],
    };
    expect(fileStanding(mixed)).toBe(
      "10 values wait for a decision. 2 values belong to an open conflict and are decided there, under Conflicts. Decided so far: 6 values accepted.",
    );
    const onlyConflict: ReviewFile = { ...SUPPLIERS, columns: [column("country", { pending: 1, in_conflict: 1 })] };
    expect(fileStanding(onlyConflict)).toBe(
      "1 value belongs to an open conflict and is decided there, under Conflicts.",
    );
    expect(fileTotals(onlyConflict).decidable).toBe(0);
  });

  it("labels the button with what it will decide", () => {
    expect(decideAllLabel("accepted", 4)).toBe("Accept all 4 waiting values");
    expect(decideAllLabel("rejected", 2400)).toBe("Reject all 2,400 waiting values");
    expect(decideAllLabel("accepted", 1)).toBe("Accept the 1 waiting value");
  });
});

describe("what stops a decision before it is sent", () => {
  const base = { file: SUPPLIERS, decision: "accepted", rationale: REASON, kind: null, keyColumn: null } as const;

  it("is a missing reason", () => {
    expect(decisionBlocker({ ...base, rationale: "" })).toBe("Give the reason for the decision first.");
    expect(decisionBlocker({ ...base, rationale: "  ok " })).toBe("Give the reason for the decision first.");
    expect(decisionBlocker({ ...base, decision: "rejected", rationale: " " })).toBe(
      "Give the reason for the decision first.",
    );
    expect(decisionBlocker(base)).toBeNull();
  });

  it("is a file that has not been told what its rows are", () => {
    const unknown = { ...base, file: UNKNOWN };
    expect(decisionBlocker(unknown)).toBe("Choose what each row of this file is.");
    expect(decisionBlocker({ ...unknown, kind: SUPPLIER_KIND })).toBe(
      "Choose the column that identifies each supplier.",
    );
    expect(decisionBlocker({ ...unknown, kind: SUPPLIER_KIND, keyColumn: "Lieferant Nr" })).toBeNull();
    // The kind asked for already names a column as the identifier.
    const proposed: ReviewFile = { ...UNKNOWN, entity: "Supplier", entity_source: "proposed", key_field: "supplier_id", key_column: "Lieferant Nr" };
    expect(decisionBlocker({ ...base, file: proposed, kind: SUPPLIER_KIND })).toBeNull();
  });

  it("is never the kind of record for a rejection", () => {
    expect(decisionBlocker({ ...base, file: UNKNOWN, decision: "rejected" })).toBeNull();
  });
});

describe("what is sent", () => {
  const base = { file: SUPPLIERS, decision: "accepted", rationale: `  ${REASON} `, kind: null, keyColumn: null } as const;

  it("is the decision, the reason and the file, for every column", () => {
    expect(buildDecision(base)).toEqual({ decision: "accepted", rationale: REASON, source_file_id: "file-1" });
  });

  it("names the columns when only some are decided", () => {
    expect(buildDecision({ ...base, decision: "rejected", columns: ["country"] })).toEqual({
      decision: "rejected",
      rationale: REASON,
      source_file_id: "file-1",
      source_columns: ["country"],
    });
  });

  it("carries a field name only where the reviewer changed it", () => {
    const body = buildDecision({
      ...base,
      fields: { supplier_name: " legal_name ", country: "country", supplier_id: "" },
    });
    expect(body.canonical_fields).toEqual({ supplier_name: "legal_name" });
    expect(body.canonical_entity).toBeUndefined();
  });

  it("leaves out names of columns that are not part of the decision", () => {
    const decided: ReviewFile = {
      ...SUPPLIERS,
      columns: [
        column("supplier_id", { role: "key" }),
        column("supplier_name", { pending: 0, accepted: 6 }),
        column("country"),
      ],
    };
    // Typed for a column outside the decision, and for one with nothing left to decide.
    expect(
      buildDecision({ ...base, file: decided, columns: ["supplier_id"], fields: { country: "nation" } }).canonical_fields,
    ).toBeUndefined();
    expect(buildDecision({ ...base, file: decided, fields: { supplier_name: "legal_name" } }).canonical_fields).toBeUndefined();
  });

  it("sends no kind and no names with a rejection", () => {
    expect(
      buildDecision({
        ...base,
        file: UNKNOWN,
        decision: "rejected",
        kind: SUPPLIER_KIND,
        keyColumn: "Lieferant Nr",
        fields: { Firma: "supplier_name" },
      }),
    ).toEqual({ decision: "rejected", rationale: REASON, source_file_id: "file-3" });
  });

  it("tells a file nothing recognises what its rows are and which column identifies them", () => {
    expect(
      buildDecision({
        ...base,
        file: UNKNOWN,
        kind: SUPPLIER_KIND,
        keyColumn: "Lieferant Nr",
        fields: { Firma: "supplier_name" },
      }),
    ).toEqual({
      decision: "accepted",
      rationale: REASON,
      source_file_id: "file-3",
      canonical_entity: "Supplier",
      canonical_fields: { Firma: "supplier_name", "Lieferant Nr": "supplier_id" },
    });
  });

  it("does not name the identifying column when it is not part of the decision", () => {
    const body = buildDecision({ ...base, file: UNKNOWN, kind: SUPPLIER_KIND, keyColumn: "Lieferant Nr", columns: ["Land"] });
    expect(body.canonical_fields).toBeUndefined();
    expect(body.canonical_entity).toBe("Supplier");
  });

  it("does not repeat the kind once the file has it", () => {
    const reviewed: ReviewFile = { ...UNKNOWN, entity: "Supplier", entity_source: "review", key_field: "supplier_id", key_column: "Lieferant Nr" };
    const body = buildDecision({ ...base, file: reviewed, kind: SUPPLIER_KIND, keyColumn: "Lieferant Nr" });
    expect(body.canonical_entity).toBeUndefined();
    expect(body.canonical_fields).toBeUndefined();
  });
});

describe("what a recorded decision is reported as", () => {
  const result: ColumnDecisionResult = {
    decision: "accepted",
    source_file_id: "file-1",
    canonical_entity: "Supplier",
    columns: { supplier_id: "supplier_id", supplier_name: "supplier_name" },
    claims_decided: 4,
    claims_left_in_conflict: 0,
    conflicts_detected: 0,
    readiness: "ready",
    explanation: "",
  };

  it("says how many values, in which columns of which file", () => {
    expect(decisionNotice(result, "suppliers.csv")).toBe(
      "4 values in 2 columns of suppliers.csv accepted, recorded with your reason.",
    );
    expect(
      decisionNotice({ ...result, decision: "rejected", columns: { country: null }, claims_decided: 2 }, "suppliers.csv"),
    ).toBe("2 values in the column country of suppliers.csv rejected, recorded with your reason.");
    expect(decisionNotice({ ...result, claims_decided: 1200, columns: { a: "a", b: "b", c: "c" } }, "bulk.csv")).toBe(
      "1,200 values in 3 columns of bulk.csv accepted, recorded with your reason.",
    );
    expect(decisionNotice({ ...result, claims_decided: 1, columns: { country: "country" } }, "one.csv")).toBe(
      "1 value in the column country of one.csv accepted, recorded with your reason.",
    );
  });

  it("says when rows were found to disagree", () => {
    expect(decisionNotice({ ...result, conflicts_detected: 1 }, "suppliers.csv")).toBe(
      "4 values in 2 columns of suppliers.csv accepted, recorded with your reason. 1 conflict between rows was found: resolve it below before publishing.",
    );
    expect(decisionNotice({ ...result, conflicts_detected: 2 }, "suppliers.csv")).toContain(
      "2 conflicts between rows were found: resolve them below before publishing.",
    );
  });

  it("says when values were left to an open conflict", () => {
    expect(decisionNotice({ ...result, claims_left_in_conflict: 2 }, "suppliers.csv")).toBe(
      "4 values in 2 columns of suppliers.csv accepted, recorded with your reason. 2 values in an open conflict were left to it.",
    );
    expect(decisionNotice({ ...result, claims_left_in_conflict: 1 }, "suppliers.csv")).toContain(
      "1 value in an open conflict was left to it.",
    );
  });
});
