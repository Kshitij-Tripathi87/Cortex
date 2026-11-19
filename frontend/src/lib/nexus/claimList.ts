/**
 * The values of an upload, a page at a time.
 *
 * Every cell of an uploaded file is a value that waits for a decision. The
 * review page asked for all of them and drew a table row for each: a file of
 * 3,000 rows and eight columns is 24,000 rows, and the browser tab was killed
 * drawing them. The page now asks for one page of values, narrowed to what
 * the reviewer is looking for, and for the counts separately.
 *
 * This file holds what the page says and asks for; it has no state.
 */

/** How many values one request brings, and one press of "show more" adds. */
export const CLAIM_PAGE = 100;

/** The most values the API returns for one request. */
export const CLAIM_PAGE_MAX = 500;

/** How many open conflicts are drawn at once. */
export const CONFLICTS_SHOWN = 25;

/**
 * How long the site waits for an upload, for preparing, deciding and
 * publishing. Each works through every value of a file: a few seconds for a
 * few thousand rows, about forty for the quarter of a million values a file
 * may hold. Ordinary requests give up after fifteen seconds, which reported a
 * failure while the server finished the work.
 */
export const LONG_ACTION_TIMEOUT_MS = 180_000;

/** Said while such a request is under way. */
export const LONG_ACTION_NOTE = "A large file can take a minute. The page updates when it is done.";

export type ClaimStateFilter = "all" | "pending_review" | "accepted" | "rejected" | "superseded";

export interface ClaimFilters {
  state: ClaimStateFilter;
  /** A source column, or "" for every column. */
  column: string;
  /** As typed: a row number, or "". */
  row: string;
  /** As typed: a text the value contains, or "". */
  value: string;
}

export const NO_FILTERS: ClaimFilters = { state: "all", column: "", row: "", value: "" };

/** Counts of the values of a batch, as `GET …/claims/summary` returns them. */
export interface ClaimSummary {
  total: number;
  pending_review: number;
  accepted: number;
  rejected: number;
  superseded: number;
}

export const STATE_CHOICES: { value: ClaimStateFilter; label: string }[] = [
  { value: "all", label: "All values" },
  { value: "pending_review", label: "Waiting" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "superseded", label: "Withdrawn" },
];

/** Whether two sets of filters ask for the same list. */
export function sameFilters(left: ClaimFilters, right: ClaimFilters): boolean {
  return (
    left.state === right.state &&
    left.column === right.column &&
    left.row.trim() === right.row.trim() &&
    left.value.trim() === right.value.trim()
  );
}

export function hasFilters(filters: ClaimFilters): boolean {
  return (
    filters.state !== "all" ||
    filters.column !== "" ||
    filters.row.trim() !== "" ||
    filters.value.trim() !== ""
  );
}

/** The row typed, as a number from 1, or null when it is not one. */
export function rowNumber(row: string): number | null {
  const typed = row.trim();
  if (!/^\d{1,9}$/.test(typed)) return null;
  const parsed = Number(typed);
  return parsed >= 1 ? parsed : null;
}

/** Why the row typed cannot be searched for, or null when it can (or is empty). */
export function rowProblem(row: string): string | null {
  if (row.trim() === "") return null;
  return rowNumber(row) === null ? "A row is a whole number from 1, as in the file." : null;
}

/**
 * The filters as the API takes them, without the state: the counts are asked
 * for with these, and the state is then read from the counts.
 */
export function filterQuery(filters: ClaimFilters): Record<string, string> {
  const query: Record<string, string> = {};
  if (filters.column) query.source_column = filters.column;
  const row = rowNumber(filters.row);
  if (row !== null) query.row_number = String(row);
  const value = filters.value.trim();
  if (value) query.value = value;
  return query;
}

/** One page of values: the filters, the state, and where the page starts. */
export function pageQuery(filters: ClaimFilters, limit: number, offset: number): Record<string, string> {
  const query = filterQuery(filters);
  if (filters.state !== "all") query.claim_state = filters.state;
  query.limit = String(Math.max(1, Math.min(CLAIM_PAGE_MAX, Math.floor(limit))));
  if (offset > 0) query.offset = String(Math.floor(offset));
  return query;
}

/** How many values match the filters, from the counts taken with `filterQuery`. */
export function matching(summary: ClaimSummary | null, state: ClaimStateFilter): number | null {
  if (!summary) return null;
  return state === "all" ? summary.total : summary[state];
}

/**
 * How many values to ask for when the table is loaded again after a decision:
 * as many as the reviewer had brought up, so the place is kept, within what
 * one request may bring.
 */
export function reloadSize(shown: number): number {
  return Math.max(CLAIM_PAGE, Math.min(CLAIM_PAGE_MAX, shown));
}

/** How many more values the next press brings, or 0 when all are shown. */
export function nextPageSize(shown: number, total: number | null): number {
  if (total === null) return 0;
  return Math.max(0, Math.min(CLAIM_PAGE, total - shown));
}

const count = (value: number): string => value.toLocaleString("en-US");

/** The line under the table: how much of what there is has been drawn. */
export function showingLine(shown: number, total: number | null, filtered: boolean): string {
  if (total === null) return shown === 1 ? "1 value shown." : `${count(shown)} values shown.`;
  if (total === 0) return filtered ? "No value matches." : "No values.";
  const noun = total === 1 ? "value" : "values";
  const scope = filtered ? `${noun} that match` : noun;
  if (shown >= total) {
    if (total === 1) return filtered ? "The 1 value that matches is shown." : "The 1 value is shown.";
    return filtered ? `All ${count(total)} values that match are shown.` : `All ${count(total)} values are shown.`;
  }
  return `Showing ${count(shown)} of ${count(total)} ${scope}, in file order.`;
}

/** The note above the conflicts when not all of them are drawn. */
export function conflictsLine(shown: number, total: number): string | null {
  if (total <= shown) return null;
  return `The first ${count(shown)} of ${count(total)} open conflicts. The rest appear here as these are decided.`;
}
