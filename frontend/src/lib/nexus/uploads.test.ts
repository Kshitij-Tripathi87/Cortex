import { describe, expect, it } from "vitest";
import {
  uploadListSummary,
  uploadName,
  uploadRows,
  uploadStatus,
  type UploadBatch,
} from "./uploads";

function batch(overrides: Partial<UploadBatch>): UploadBatch {
  return {
    batch_id: "b-1",
    files: [{ name: "suppliers.csv", rows: 6 }],
    uploaded_at: "2026-11-17T09:00:00+00:00",
    state: "published",
    published_version: 1,
    claims_accepted: 42,
    claims_pending_review: 0,
    claims_rejected: 0,
    open_conflicts: 0,
    blocking_conflicts: 0,
    ...overrides,
  };
}

describe("uploadStatus", () => {
  it("says which version a published upload became", () => {
    expect(uploadStatus(batch({}))).toEqual({
      label: "Published · version 1",
      tone: "done",
      detail: "42 values accepted and part of your data.",
      action: "Open",
    });
  });

  it("counts what waits for review, with singular and plural", () => {
    const waiting = uploadStatus(
      batch({ state: "review_required", published_version: null, claims_pending_review: 36, open_conflicts: 1 }),
    );
    expect(waiting.label).toBe("Waiting for review");
    expect(waiting.tone).toBe("todo");
    expect(waiting.detail).toBe("36 values wait for a decision and 1 conflict is open. Not part of your data yet.");
    expect(waiting.action).toBe("Review");

    const one = uploadStatus(batch({ state: "review_required", published_version: null, claims_pending_review: 1 }));
    expect(one.detail).toBe("1 value waits for a decision. Not part of your data yet.");
  });

  it("says that a reviewed upload is not part of the data until it is published", () => {
    const ready = uploadStatus(batch({ state: "ready_to_publish", published_version: null }));
    expect(ready.label).toBe("Ready to publish");
    expect(ready.detail).toBe(
      "Every value is reviewed (42 values accepted). It is not part of your data until you publish it.",
    );
    expect(ready.action).toBe("Open and publish");
  });

  it("names what blocks a blocked upload", () => {
    const blocked = uploadStatus(batch({ state: "blocked", published_version: null, blocking_conflicts: 2 }));
    expect(blocked).toEqual({
      label: "Blocked",
      tone: "blocked",
      detail: "2 conflicts must be resolved before this can be published.",
      action: "Resolve",
    });
  });

  it("explains the two states with nothing to publish", () => {
    expect(uploadStatus(batch({ state: "not_prepared", published_version: null, claims_accepted: 0 })).action).toBe(
      "Open and prepare",
    );
    expect(uploadStatus(batch({ state: "nothing_accepted", published_version: null, claims_accepted: 0 })).detail).toBe(
      "Every value was rejected, so there is nothing to publish.",
    );
  });

  it("shows an unknown state as written instead of guessing", () => {
    expect(uploadStatus(batch({ state: "under_legal_hold" }))).toEqual({
      label: "under legal hold",
      tone: "idle",
      detail: "",
      action: "Open",
    });
  });
});

describe("uploadName and uploadRows", () => {
  it("joins file names and adds up their rows", () => {
    const two = batch({ files: [{ name: "a.csv", rows: 5 }, { name: "b.csv", rows: 1 }] });
    expect(uploadName(two)).toBe("a.csv and b.csv");
    expect(uploadRows(two)).toBe("6 rows");
    expect(uploadRows(batch({ files: [{ name: "a.csv", rows: 1 }] }))).toBe("1 row");
  });

  it("copes with an upload that has no file row or no row count", () => {
    expect(uploadName(batch({ files: [] }))).toBe("Upload without a file name");
    expect(uploadRows(batch({ files: [] }))).toBeNull();
    expect(uploadRows(batch({ files: [{ name: "a.csv", rows: null }] }))).toBeNull();
  });
});

describe("uploadListSummary", () => {
  it("counts the uploads and those not published", () => {
    expect(uploadListSummary({ batch_count: 0, batches: [] })).toBe("No uploads yet");
    expect(uploadListSummary({ batch_count: 1, batches: [batch({})] })).toBe("1 upload · all published");
    expect(
      uploadListSummary({
        batch_count: 3,
        batches: [batch({}), batch({ state: "blocked" }), batch({ state: "review_required" })],
      }),
    ).toBe("3 uploads · 2 not published");
  });

  it("says when the list is shorter than the total", () => {
    expect(uploadListSummary({ batch_count: 40, batches: [batch({}), batch({})] })).toBe(
      "40 uploads · showing the 2 most recent",
    );
  });
});
