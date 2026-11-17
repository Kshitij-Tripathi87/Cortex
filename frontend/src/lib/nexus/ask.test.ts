import { describe, expect, it } from "vitest";

import { askPlaceholder, askSuggestions, evidenceSummary, evidenceTool } from "./ask";

describe("askSuggestions", () => {
  it("offers complete questions the assistant answers from published data", () => {
    const questions = askSuggestions(null);
    expect(questions).toEqual([
      "What changed?",
      "Which orders are exposed?",
      "Which orders are late?",
      "What is below safety stock?",
    ]);
    // Nothing refers to a selection the server cannot see.
    expect(questions.join(" ")).not.toMatch(/selected/i);
  });

  it("names the selected record by identifier, first", () => {
    const questions = askSuggestions({ entity_id: "S-101", entity_name: "Bharat Castings" });
    expect(questions[0]).toBe("What does the data show about S-101?");
    expect(questions).toHaveLength(5);
  });

  it("ignores a selection without an identifier", () => {
    expect(askSuggestions({ entity_id: "  " })).toHaveLength(4);
  });
});

describe("askPlaceholder", () => {
  it("uses the identifier of the selected record", () => {
    expect(askPlaceholder({ entity_id: "S-101", entity_name: "Bharat Castings" })).toBe(
      "Why is S-101 affected?",
    );
    expect(askPlaceholder(null)).toBe("Ask about the data in this workspace");
  });
});

describe("evidenceSummary", () => {
  it("prefers the summary line written by the server", () => {
    expect(
      evidenceSummary({
        tool: "nexus.graph.read",
        summary: "Read 28 published records from version 5; matched S-101 Bharat Castings Pvt Ltd.",
        data_excerpt: '{"workspace_data": {"question_focus": ...(truncated)',
      }),
    ).toBe("Read 28 published records from version 5; matched S-101 Bharat Castings Pvt Ltd.");
  });

  it("falls back to the first fields of a raw excerpt object", () => {
    expect(
      evidenceSummary({ data_excerpt: { count: 2, risks: [{ id: 1 }, { id: 2 }], meta: { a: 1 } } }),
    ).toBe("count: 2 · risks: 2 items · meta: 1 fields");
  });

  it("shortens long text and never returns an empty string", () => {
    const long = "x".repeat(400);
    const shortened = evidenceSummary({ data_excerpt: long }, 50);
    expect(shortened).toHaveLength(50);
    expect(shortened.endsWith("…")).toBe(true);
    expect(evidenceSummary({})).toBe("—");
    expect(evidenceSummary({ summary: "   ", data_excerpt: "" })).toBe("—");
  });
});

describe("evidenceTool", () => {
  it("returns the tool name or a numbered fallback", () => {
    expect(evidenceTool({ tool: "nexus.risk.read" }, 0)).toBe("nexus.risk.read");
    expect(evidenceTool({}, 2)).toBe("evidence_3");
  });
});
