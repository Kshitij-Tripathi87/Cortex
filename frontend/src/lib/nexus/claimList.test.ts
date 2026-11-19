import { describe, expect, it } from "vitest";
import {
  CLAIM_PAGE,
  CLAIM_PAGE_MAX,
  LONG_ACTION_TIMEOUT_MS,
  NO_FILTERS,
  STATE_CHOICES,
  conflictsLine,
  filterQuery,
  hasFilters,
  matching,
  nextPageSize,
  pageQuery,
  reloadSize,
  rowNumber,
  rowProblem,
  sameFilters,
  showingLine,
  type ClaimSummary,
} from "./claimList";

const SUMMARY: ClaimSummary = { total: 24000, pending_review: 21000, accepted: 2400, rejected: 590, superseded: 10 };

describe("what the table asks for", () => {
  it("asks for one page and nothing else when nothing is narrowed", () => {
    expect(pageQuery(NO_FILTERS, CLAIM_PAGE, 0)).toEqual({ limit: "100" });
    expect(filterQuery(NO_FILTERS)).toEqual({});
    expect(hasFilters(NO_FILTERS)).toBe(false);
  });

  it("sends each filter under the name the API reads", () => {
    const filters = { state: "pending_review", column: "country", row: " 17 ", value: "  on_hold " } as const;
    expect(pageQuery(filters, CLAIM_PAGE, 200)).toEqual({
      claim_state: "pending_review",
      source_column: "country",
      row_number: "17",
      value: "on_hold",
      limit: "100",
      offset: "200",
    });
    // The counts are taken without the state and read per state afterwards.
    expect(filterQuery(filters)).toEqual({ source_column: "country", row_number: "17", value: "on_hold" });
    expect(hasFilters(filters)).toBe(true);
  });

  it("keeps a page within what one request may bring", () => {
    expect(pageQuery(NO_FILTERS, 5000, 0).limit).toBe(String(CLAIM_PAGE_MAX));
    expect(pageQuery(NO_FILTERS, 0, 0).limit).toBe("1");
    expect(pageQuery(NO_FILTERS, 250.7, 0).limit).toBe("250");
  });

  it("does not send a row that is not a row", () => {
    for (const typed of ["abc", "0", "-3", "1.5", "12a", "1e3"]) {
      expect(rowNumber(typed), typed).toBeNull();
      expect(rowProblem(typed), typed).toBe("A row is a whole number from 1, as in the file.");
      expect(filterQuery({ ...NO_FILTERS, row: typed })).toEqual({});
      // Still a filter: the table says why nothing was searched.
      expect(hasFilters({ ...NO_FILTERS, row: typed })).toBe(true);
    }
    expect(rowNumber("2517")).toBe(2517);
    expect(rowProblem("")).toBeNull();
    expect(rowProblem("   ")).toBeNull();
    expect(hasFilters({ ...NO_FILTERS, row: "   ", value: "  " })).toBe(false);
  });

  it("knows when the table still shows the answer to an earlier question", () => {
    const typed = { state: "all", column: "status", row: "", value: "hold" } as const;
    expect(sameFilters(NO_FILTERS, NO_FILTERS)).toBe(true);
    expect(sameFilters(typed, { ...typed })).toBe(true);
    // Spaces around what was typed ask for nothing new.
    expect(sameFilters(typed, { ...typed, value: " hold ", row: "  " })).toBe(true);
    expect(sameFilters(typed, NO_FILTERS)).toBe(false);
    expect(sameFilters(typed, { ...typed, state: "rejected" })).toBe(false);
    expect(sameFilters(typed, { ...typed, column: "country" })).toBe(false);
    expect(sameFilters(typed, { ...typed, row: "7" })).toBe(false);
    expect(sameFilters(typed, { ...typed, value: "holds" })).toBe(false);
  });

  it("offers every state a value can be in", () => {
    expect(STATE_CHOICES.map((choice) => choice.value)).toEqual([
      "all",
      "pending_review",
      "accepted",
      "rejected",
      "superseded",
    ]);
    expect(STATE_CHOICES.map((choice) => choice.label)).toEqual([
      "All values",
      "Waiting",
      "Accepted",
      "Rejected",
      "Withdrawn",
    ]);
  });
});

describe("requests that work through a whole file", () => {
  it("are given longer than the fifteen seconds an ordinary request gets", () => {
    // Preparing, accepting or publishing 240,000 values takes about forty seconds.
    expect(LONG_ACTION_TIMEOUT_MS).toBeGreaterThanOrEqual(120_000);
  });
});

describe("how many values there are", () => {
  it("reads the state from the counts", () => {
    expect(matching(SUMMARY, "all")).toBe(24000);
    expect(matching(SUMMARY, "pending_review")).toBe(21000);
    expect(matching(SUMMARY, "accepted")).toBe(2400);
    expect(matching(SUMMARY, "rejected")).toBe(590);
    expect(matching(SUMMARY, "superseded")).toBe(10);
    expect(matching(null, "all")).toBeNull();
  });

  it("brings a hundred more until none are left", () => {
    expect(nextPageSize(100, 24000)).toBe(100);
    expect(nextPageSize(23950, 24000)).toBe(50);
    expect(nextPageSize(24000, 24000)).toBe(0);
    expect(nextPageSize(48, 48)).toBe(0);
    expect(nextPageSize(100, null)).toBe(0);
    // A count that fell behind the table (a value decided elsewhere).
    expect(nextPageSize(120, 100)).toBe(0);
  });

  it("keeps the reviewer's place when the table is loaded again", () => {
    expect(reloadSize(0)).toBe(100);
    expect(reloadSize(48)).toBe(100);
    expect(reloadSize(300)).toBe(300);
    expect(reloadSize(2400)).toBe(CLAIM_PAGE_MAX);
  });
});

describe("what the table says about itself", () => {
  it("says how much of the file is drawn", () => {
    expect(showingLine(100, 24000, false)).toBe("Showing 100 of 24,000 values, in file order.");
    expect(showingLine(48, 48, false)).toBe("All 48 values are shown.");
    expect(showingLine(1, 1, false)).toBe("The 1 value is shown.");
    expect(showingLine(0, 0, false)).toBe("No values.");
  });

  it("says so when the count is of what matches", () => {
    expect(showingLine(100, 590, true)).toBe("Showing 100 of 590 values that match, in file order.");
    expect(showingLine(3, 3, true)).toBe("All 3 values that match are shown.");
    expect(showingLine(1, 1, true)).toBe("The 1 value that matches is shown.");
    expect(showingLine(0, 0, true)).toBe("No value matches.");
  });

  it("does not invent a total it was not given", () => {
    expect(showingLine(100, null, false)).toBe("100 values shown.");
    expect(showingLine(1, null, true)).toBe("1 value shown.");
  });

  it("says when not every conflict is drawn", () => {
    expect(conflictsLine(25, 25)).toBeNull();
    expect(conflictsLine(3, 3)).toBeNull();
    expect(conflictsLine(25, 1310)).toBe(
      "The first 25 of 1,310 open conflicts. The rest appear here as these are decided.",
    );
  });
});
