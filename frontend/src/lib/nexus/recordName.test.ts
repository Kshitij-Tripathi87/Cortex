import { describe, expect, it } from "vitest";
import { recordName } from "./recordName";

describe("recordName", () => {
  it("reads the name from the column a file of that kind uses", () => {
    expect(recordName({ supplier_id: "S-100", supplier_name: "Acme Metals GmbH" }, "S-100")).toBe("Acme Metals GmbH");
    expect(recordName({ sku: "C-2000", product_name: "Cast Iron Housing" }, "C-2000")).toBe("Cast Iron Housing");
    expect(recordName({ warehouse_name: "Pune Plant Store", city: "Pune" }, "WH-PUNE")).toBe("Pune Plant Store");
    expect(recordName({ legal_name: "Bharat Castings Pvt Ltd" }, "S-101")).toBe("Bharat Castings Pvt Ltd");
  });

  it("prefers a plain name, and a name over a description", () => {
    expect(recordName({ name: "Plain", supplier_name: "Other" }, "X")).toBe("Plain");
    expect(recordName({ description: "A long text", product_name: "Seal Kit" }, "X")).toBe("Seal Kit");
    expect(recordName({ description: "Only a description" }, "X")).toBe("Only a description");
  });

  it("falls back to the identifier when the record has no name", () => {
    expect(recordName({ quantity: "400", status: "delayed" }, "PO-5001")).toBe("PO-5001");
    expect(recordName({}, "PO-5001")).toBe("PO-5001");
    expect(recordName(null, "PO-5001")).toBe("PO-5001");
    expect(recordName(undefined, "PO-5001")).toBe("PO-5001");
  });

  it("ignores empty and non-text values", () => {
    expect(recordName({ name: "   ", supplier_name: "Acme" }, "X")).toBe("Acme");
    expect(recordName({ name: 42, supplier_name: null, legal_name: "Acme" }, "X")).toBe("Acme");
    expect(recordName({ name: "  Acme  " }, "X")).toBe("Acme");
  });
});
