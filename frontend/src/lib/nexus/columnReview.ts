/**
 * An upload reviewed by column: what the page says and what it sends.
 *
 * Every cell of an uploaded file waits for a decision. Reviewing them one by
 * one took a dialog per cell, with the kind of record typed by hand. A
 * reviewer decides what a column means, so the page shows one row per column
 * and records one decision for all of its values.
 *
 * This file has no state. It reads the answer of
 * `GET /sources/batches/{id}/columns` and builds the body of
 * `POST /sources/batches/{id}/columns/review`.
 */

export interface ReviewColumn {
  source_column: string;
  /** The field its values are published under. */
  canonical_field: string;
  /** "key" identifies the record of each row, "link" names another record, "value" is a plain field. */
  role: "key" | "link" | "value" | string;
  links_to: string | null;
  examples: string[];
  pending: number;
  accepted: number;
  rejected: number;
  superseded: number;
  /** Waiting values that belong to an open conflict and are decided there. */
  in_conflict: number;
}

export interface ReviewFile {
  file_id: string;
  name: string;
  rows: number | null;
  /** The kind of record each row describes; null when nothing says so yet. */
  entity: string | null;
  /** "columns": recognised from the column names. "review": set by an accepted decision. "proposed": only asked for. */
  entity_source: "columns" | "review" | "proposed" | string | null;
  key_field: string | null;
  key_column: string | null;
  /** Why the file cannot be reviewed by column, when it cannot. */
  problem: string | null;
  columns: ReviewColumn[];
}

export interface RecordKind {
  entity: string;
  key_field: string;
}

export interface ColumnReviewView {
  batch_id: string;
  files: ReviewFile[];
  record_kinds: RecordKind[];
}

export interface ColumnDecisionResult {
  decision: string;
  source_file_id: string;
  canonical_entity: string | null;
  /** Column -> field it was accepted under; null for a rejected column. */
  columns: Record<string, string | null>;
  claims_decided: number;
  claims_left_in_conflict: number;
  conflicts_detected: number;
  readiness: string;
  explanation: string;
}

/** What the reviewer has chosen when a decision is asked for. */
export interface DecisionInput {
  file: ReviewFile;
  decision: "accepted" | "rejected";
  rationale: string;
  /** The columns decided; left out for every column of the file. */
  columns?: string[];
  /** Field names the reviewer typed, by source column. */
  fields?: Record<string, string>;
  /** For a file whose columns do not say what its rows are: the kind chosen. */
  kind: RecordKind | null;
  /** For such a file: the column chosen to identify each record. */
  keyColumn: string | null;
}

export interface ColumnDecisionBody {
  decision: "accepted" | "rejected";
  rationale: string;
  source_file_id: string;
  source_columns?: string[];
  canonical_entity?: string;
  canonical_fields?: Record<string, string>;
}

const number = (value: number): string => value.toLocaleString("en-US");

/** "1 value", "1,200 values". */
function count(value: number, noun: string): string {
  return `${number(value)} ${noun}${value === 1 ? "" : "s"}`;
}

/** "PurchaseOrder" -> "purchase order". */
export function kindLabel(entity: string): string {
  return entity
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/_/g, " ")
    .toLowerCase()
    .trim();
}

/** "Supplier" -> "a supplier", "InventoryItem" -> "an inventory item". */
export function aKind(entity: string): string {
  const label = kindLabel(entity);
  return `${/^[aeiou]/.test(label) ? "an" : "a"} ${label}`;
}

/** Whether something other than the reviewer's choice on this page says what the rows are. */
export function kindIsSettled(file: ReviewFile): boolean {
  return file.entity !== null && (file.entity_source === "columns" || file.entity_source === "review");
}

/** Values of a column that one decision here can decide: waiting and not in a conflict. */
export function decidable(column: ReviewColumn): number {
  return Math.max(0, column.pending - column.in_conflict);
}

export interface FileTotals {
  pending: number;
  accepted: number;
  rejected: number;
  superseded: number;
  inConflict: number;
  decidable: number;
}

export function fileTotals(file: ReviewFile): FileTotals {
  const totals: FileTotals = { pending: 0, accepted: 0, rejected: 0, superseded: 0, inConflict: 0, decidable: 0 };
  for (const column of file.columns) {
    totals.pending += column.pending;
    totals.accepted += column.accepted;
    totals.rejected += column.rejected;
    totals.superseded += column.superseded;
    totals.inConflict += Math.min(column.in_conflict, column.pending);
    totals.decidable += decidable(column);
  }
  return totals;
}

/** The sentence at the top of a file: what its rows are and how that is known. */
export function fileHeadline(file: ReviewFile): string {
  if (file.entity && kindIsSettled(file)) {
    const what = `Each row of ${file.name} is ${aKind(file.entity)}`;
    if (!file.key_column) {
      return `${what}, but no column holds the ${file.key_field ?? "identifier"} that identifies each one.`;
    }
    return file.entity_source === "columns"
      ? `${what}, recognised from the column ${file.key_column}.`
      : `${what}, identified by the column ${file.key_column}.`;
  }
  return `The column names of ${file.name} do not say what each row is. Choose what a row is, and the column that identifies each one.`;
}

/** What a column is to the record of its row, in a few words. */
export function columnMeaning(column: ReviewColumn, file: ReviewFile): string {
  if (!file.entity) return "";
  const record = kindLabel(file.entity);
  if (column.role === "key") return `identifies each ${record}`;
  if (column.role === "link" && column.links_to) return `links each ${record} to ${aKind(column.links_to)}`;
  return `a field of the ${record}`;
}

/** Where a file stands: how many values wait, and what was decided. */
export function fileStanding(file: ReviewFile): string {
  const totals = fileTotals(file);
  const decided: string[] = [];
  if (totals.accepted > 0) decided.push(`${count(totals.accepted, "value")} accepted`);
  if (totals.rejected > 0) decided.push(`${count(totals.rejected, "value")} rejected`);
  if (totals.superseded > 0) decided.push(`${count(totals.superseded, "value")} withdrawn`);

  if (totals.pending === 0) {
    if (decided.length === 0) return "This file has no values to decide.";
    return `Every value is decided: ${decided.join(", ")}.`;
  }
  const parts: string[] = [];
  if (totals.decidable > 0) {
    parts.push(`${count(totals.decidable, "value")} ${totals.decidable === 1 ? "waits" : "wait"} for a decision.`);
  }
  if (totals.inConflict > 0) {
    parts.push(
      `${count(totals.inConflict, "value")} ${totals.inConflict === 1 ? "belongs" : "belong"} to an open conflict and ${totals.inConflict === 1 ? "is" : "are"} decided there, under Conflicts.`,
    );
  }
  if (decided.length > 0) parts.push(`Decided so far: ${decided.join(", ")}.`);
  return parts.join(" ");
}

/** The label of the button that decides every waiting value of a file. */
export function decideAllLabel(decision: "accepted" | "rejected", waiting: number): string {
  const verb = decision === "accepted" ? "Accept" : "Reject";
  return waiting === 1 ? `${verb} the 1 waiting value` : `${verb} all ${number(waiting)} waiting values`;
}

/** Why a decision cannot be sent yet, in the reviewer's words; null when it can. */
export function decisionBlocker(input: DecisionInput): string | null {
  if (input.rationale.trim().length < 3) return "Give the reason for the decision first.";
  if (input.decision === "accepted" && !kindIsSettled(input.file)) {
    if (!input.kind) return "Choose what each row of this file is.";
    if (!(input.keyColumn ?? input.file.key_column)) {
      return `Choose the column that identifies each ${kindLabel(input.kind.entity)}.`;
    }
  }
  return null;
}

/** The body of the request that records the decision. */
export function buildDecision(input: DecisionInput): ColumnDecisionBody {
  const { file, decision, columns, fields, kind, keyColumn } = input;
  const body: ColumnDecisionBody = {
    decision,
    rationale: input.rationale.trim(),
    source_file_id: file.file_id,
  };
  if (columns) body.source_columns = columns;
  // A rejection takes no kind of record and no field names.
  if (decision !== "accepted") return body;

  const settled = kindIsSettled(file);
  if (!settled && kind) body.canonical_entity = kind.entity;

  const chosen = columns ? new Set(columns) : null;
  const renames: Record<string, string> = {};
  for (const column of file.columns) {
    if (chosen && !chosen.has(column.source_column)) continue;
    // Nothing of this column is decided now, so its name is not being set.
    if (decidable(column) === 0) continue;
    const typed = fields?.[column.source_column]?.trim();
    if (typed && typed !== column.canonical_field) renames[column.source_column] = typed;
  }
  if (!settled && kind && keyColumn && (!chosen || chosen.has(keyColumn))) {
    // The column chosen to identify each record is published as the field
    // that identifies that kind of record.
    renames[keyColumn] = kind.key_field;
  }
  if (Object.keys(renames).length > 0) body.canonical_fields = renames;
  return body;
}

/** What a recorded decision did, for the notice above the page. */
export function decisionNotice(result: ColumnDecisionResult, fileName: string): string {
  const columns = Object.keys(result.columns).length;
  const scope = columns === 1 ? `the column ${Object.keys(result.columns)[0]}` : `${columns} columns`;
  const parts = [
    `${count(result.claims_decided, "value")} in ${scope} of ${fileName} ${result.decision}, recorded with your reason.`,
  ];
  if (result.conflicts_detected > 0) {
    parts.push(
      `${count(result.conflicts_detected, "conflict")} between rows ${result.conflicts_detected === 1 ? "was" : "were"} found: resolve ${result.conflicts_detected === 1 ? "it" : "them"} below before publishing.`,
    );
  }
  if (result.claims_left_in_conflict > 0) {
    parts.push(
      `${count(result.claims_left_in_conflict, "value")} in an open conflict ${result.claims_left_in_conflict === 1 ? "was" : "were"} left to it.`,
    );
  }
  return parts.join(" ");
}
