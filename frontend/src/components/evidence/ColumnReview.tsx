"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/auth/client";
import { LONG_ACTION_NOTE, LONG_ACTION_TIMEOUT_MS } from "@/lib/nexus/claimList";
import {
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
  type ColumnReviewView,
  type ReviewColumn,
  type ReviewFile,
} from "@/lib/nexus/columnReview";

interface ColumnReviewProps {
  batchId: string;
  workspaceId: string;
  /** Whether the signed-in person may accept or reject. */
  canReview: boolean;
  /** Changes whenever the page reloads the batch, so this view follows it. */
  refreshKey: number;
  /** A decision was recorded; the page reloads the batch and shows the notice. */
  onDecided: (notice: string) => void;
  /** The columns of the upload, in file order, once they are known. */
  onColumns?: (columns: string[]) => void;
}

const capitalised = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

/**
 * An upload reviewed by column.
 *
 * Every cell of a file waits for a decision, and the page offered one dialog
 * per cell. Here each column is one row: the field it is published under, what
 * it is to the record, a few of its values, and how many wait. One reason and
 * one click decide a column or the whole file. The table of single values
 * below stays for the exception.
 */
export function ColumnReview({
  batchId,
  workspaceId,
  canReview,
  refreshKey,
  onDecided,
  onColumns,
}: ColumnReviewProps): React.JSX.Element | null {
  const [view, setView] = useState<ColumnReviewView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rationale, setRationale] = useState("");
  // Field names the reviewer typed, by file and source column.
  const [fields, setFields] = useState<Record<string, Record<string, string>>>({});
  // For a file whose columns do not say what its rows are.
  const [kindChoice, setKindChoice] = useState("");
  const [keyChoice, setKeyChoice] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!batchId || !workspaceId) return;
    try {
      const query: Record<string, string> = { workspace_id: workspaceId };
      if (kindChoice) query.entity = kindChoice;
      setView(
        await apiClient.get<ColumnReviewView>(`/sources/batches/${encodeURIComponent(batchId)}/columns`, query),
      );
      setLoadError(null);
    } catch (requestError) {
      setLoadError(requestError instanceof Error ? requestError.message : "The columns could not be loaded.");
    }
  }, [batchId, workspaceId, kindChoice]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // The page offers the columns as a filter of its table of values.
  const columnNames = view ? view.files.flatMap((file) => file.columns.map((column) => column.source_column)) : null;
  const columnList = columnNames ? JSON.stringify([...new Set(columnNames)]) : null;
  useEffect(() => {
    if (columnList !== null && onColumns) onColumns(JSON.parse(columnList) as string[]);
    // `onColumns` is called when the columns change, not when the parent
    // passes a new function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columnList]);

  async function decide(file: ReviewFile, decision: "accepted" | "rejected", columns?: string[]) {
    if (!view || busy) return;
    const kind = view.record_kinds.find((item) => item.entity === kindChoice) ?? null;
    const input = {
      file,
      decision,
      rationale,
      columns,
      fields: fields[file.file_id],
      kind,
      keyColumn: keyChoice[file.file_id] || null,
    };
    const blocker = decisionBlocker(input);
    if (blocker) {
      setActionError(blocker);
      return;
    }
    setBusy(`${decision}:${columns ? columns.join(",") : "*"}`);
    setActionError(null);
    try {
      const result = await apiClient.post<ColumnDecisionResult>(
        `/sources/batches/${encodeURIComponent(batchId)}/columns/review`,
        buildDecision(input),
        { query: { workspace_id: workspaceId }, timeoutMs: LONG_ACTION_TIMEOUT_MS },
      );
      setFields((current) => ({ ...current, [file.file_id]: {} }));
      onDecided(decisionNotice(result, file.name));
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : "The decision could not be recorded.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) {
    return (
      <div className="mb-6 break-words border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800" role="alert" data-testid="column-review-load-error">
        The columns of this upload could not be loaded: {loadError}{" "}
        <button type="button" onClick={() => void load()} className="ml-1 underline">
          Retry
        </button>
      </div>
    );
  }
  if (!view) return null;
  const files = view.files.filter((file) => file.columns.length > 0);
  if (files.length === 0) return null;
  const kind = view.record_kinds.find((item) => item.entity === kindChoice) ?? null;

  return (
    <>
      {files.map((file) => {
        const totals = fileTotals(file);
        const settled = kindIsSettled(file);
        // For a file that does not say what its rows are: the column chosen
        // to identify each record, or the one the chosen kind already names.
        const chosenKey = settled ? null : keyChoice[file.file_id] || file.key_column || "";
        const typed = fields[file.file_id] ?? {};

        const fieldCell = (column: ReviewColumn): React.JSX.Element => {
          const isKey = settled ? column.role === "key" : chosenKey === column.source_column;
          const shown = !settled && isKey && kind ? kind.key_field : column.canonical_field;
          // A name can be given while the column is still to be decided. The
          // identifying column keeps the name that identifies the record, and
          // a column with accepted values keeps the name they were given.
          const editable = canReview && !isKey && column.accepted === 0 && decidable(column) > 0;
          if (!editable) {
            return (
              <span className="block max-w-[11rem] truncate font-mono text-xs text-slate-800" title={shown}>
                {shown}
              </span>
            );
          }
          return (
            <input
              aria-label={`Field name for ${column.source_column}`}
              value={typed[column.source_column] ?? column.canonical_field}
              onChange={(event) => {
                const value = event.target.value;
                setFields((current) => ({
                  ...current,
                  [file.file_id]: { ...(current[file.file_id] ?? {}), [column.source_column]: value },
                }));
                setActionError(null);
              }}
              maxLength={128}
              spellCheck={false}
              className="w-44 border border-slate-300 p-1.5 font-mono text-xs text-slate-900"
            />
          );
        };

        return (
          <section key={file.file_id} className="mb-6 border border-slate-200 bg-white" data-testid="column-review">
            <div className="border-b border-slate-200 p-4">
              <h2 className="font-semibold text-slate-950">Review by column</h2>
              {/* A file or column name is one word with nowhere to wrap
                  (`supplier_master_2026_11.csv`), so a sentence that names
                  one may break inside it instead of widening the page. */}
              <p className="mt-1 break-words text-sm text-slate-800" data-testid="column-review-headline">
                {fileHeadline(file)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Decide what a column means once, instead of each of its values. Rows that disagree about the same
                record are still found afterwards and block publishing until you choose between them.
              </p>
              {file.problem && (
                <p role="alert" className="mt-2 break-words text-sm text-rose-700" data-testid="column-review-problem">
                  {file.problem}
                </p>
              )}
              {!settled && !file.problem && (
                <div className="mt-3 flex flex-wrap items-end gap-3 text-xs text-slate-600">
                  <label className="flex min-w-0 flex-col gap-1">
                    Each row is
                    <select
                      value={kindChoice}
                      onChange={(event) => {
                        setKindChoice(event.target.value);
                        setActionError(null);
                      }}
                      disabled={!canReview}
                      className="max-w-[16rem] border border-slate-300 bg-white p-2 text-sm text-slate-900"
                      data-testid="column-review-kind"
                    >
                      <option value="">Choose…</option>
                      {view.record_kinds.map((item) => (
                        <option key={item.entity} value={item.entity}>
                          {capitalised(kindLabel(item.entity))}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex min-w-0 flex-col gap-1">
                    {kind ? `Column that identifies each ${kindLabel(kind.entity)}` : "Column that identifies each row"}
                    <select
                      value={chosenKey ?? ""}
                      onChange={(event) => {
                        const value = event.target.value;
                        setKeyChoice((current) => ({ ...current, [file.file_id]: value }));
                        setActionError(null);
                      }}
                      disabled={!canReview}
                      className="max-w-[16rem] border border-slate-300 bg-white p-2 text-sm text-slate-900"
                      data-testid="column-review-key"
                    >
                      <option value="">Choose…</option>
                      {file.columns.map((column) => (
                        <option key={column.source_column} value={column.source_column}>
                          {column.source_column}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="whitespace-nowrap px-4 py-3">Column</th>
                    <th className="whitespace-nowrap px-4 py-3">Examples</th>
                    <th className="whitespace-nowrap px-4 py-3">Published as</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right">Waiting</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right">Accepted</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right">Rejected</th>
                    <th className="whitespace-nowrap px-4 py-3">Decision</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {file.columns.map((column) => {
                    const waiting = decidable(column);
                    const meaning =
                      !settled && chosenKey === column.source_column && kind
                        ? `identifies each ${kindLabel(kind.entity)}`
                        : columnMeaning(column, file);
                    return (
                      <tr key={column.source_column} className="align-top" data-testid="column-review-row">
                        <td className="px-4 py-3">
                          <p className="max-w-[12rem] truncate font-medium text-slate-900" title={column.source_column}>
                            {column.source_column}
                          </p>
                          {meaning && <p className="mt-1 whitespace-nowrap text-[11px] text-slate-500">{meaning}</p>}
                        </td>
                        <td className="px-4 py-3">
                          <p className="max-w-xs truncate text-xs text-slate-700" title={column.examples.join(", ")}>
                            {column.examples.length > 0 ? column.examples.join(", ") : "—"}
                          </p>
                        </td>
                        <td className="px-4 py-3">{fieldCell(column)}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-900">
                          {column.pending.toLocaleString("en-US")}
                          {column.in_conflict > 0 && (
                            <p className="whitespace-nowrap text-[11px] text-amber-700">
                              {column.in_conflict.toLocaleString("en-US")} in a conflict
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-900">
                          {column.accepted.toLocaleString("en-US")}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-900">
                          {column.rejected.toLocaleString("en-US")}
                        </td>
                        <td className="px-4 py-3">
                          {waiting > 0 && !file.problem ? (
                            <div className="flex gap-3 whitespace-nowrap text-xs font-medium">
                              <button
                                type="button"
                                aria-label={`Accept the column ${column.source_column}`}
                                onClick={() => void decide(file, "accepted", [column.source_column])}
                                disabled={!canReview || busy !== null}
                                className="text-emerald-700 hover:underline disabled:opacity-40"
                              >
                                Accept
                              </button>
                              <button
                                type="button"
                                aria-label={`Reject the column ${column.source_column}`}
                                onClick={() => void decide(file, "rejected", [column.source_column])}
                                disabled={!canReview || busy !== null}
                                className="text-rose-700 hover:underline disabled:opacity-40"
                              >
                                Reject
                              </button>
                            </div>
                          ) : (
                            <span className="text-xs text-slate-500">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="border-t border-slate-200 p-4">
              <p className="text-xs text-slate-600" data-testid="column-review-standing">
                {fileStanding(file)}
              </p>
              {totals.decidable > 0 && !file.problem && (
                <>
                  <label htmlFor={`column-review-reason-${file.file_id}`} className="mt-3 block text-xs font-medium text-slate-700">
                    Reason for the decision (required; kept in the audit log with your name)
                  </label>
                  <input
                    id={`column-review-reason-${file.file_id}`}
                    value={rationale}
                    onChange={(event) => {
                      setRationale(event.target.value);
                      setActionError(null);
                    }}
                    maxLength={2000}
                    disabled={!canReview}
                    className="mt-1 w-full min-w-0 border border-slate-300 p-2 text-sm text-slate-900"
                    placeholder="For example: checked against the ERP export of 14 November"
                    data-testid="column-review-reason"
                  />
                  {actionError && (
                    <p role="alert" className="mt-2 break-words text-sm text-rose-700" data-testid="column-review-error">
                      {actionError}
                    </p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void decide(file, "accepted")}
                      disabled={!canReview || busy !== null}
                      className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
                      data-testid="column-review-accept-all"
                    >
                      {busy === "accepted:*" ? "Saving…" : decideAllLabel("accepted", totals.decidable)}
                    </button>
                    <button
                      type="button"
                      onClick={() => void decide(file, "rejected")}
                      disabled={!canReview || busy !== null}
                      className="rounded border border-solid border-rose-300 px-4 py-2 text-sm font-medium text-rose-700 disabled:cursor-not-allowed disabled:opacity-40"
                      data-testid="column-review-reject-all"
                    >
                      {busy === "rejected:*" ? "Saving…" : decideAllLabel("rejected", totals.decidable)}
                    </button>
                  </div>
                  {busy !== null && (
                    <p aria-live="polite" className="mt-2 text-xs text-slate-600" data-testid="column-review-working">
                      Recording the decision. {LONG_ACTION_NOTE}
                    </p>
                  )}
                  {!canReview && (
                    <p className="mt-2 text-xs text-slate-500">An admin or operator role is needed to decide.</p>
                  )}
                </>
              )}
            </div>
          </section>
        );
      })}
    </>
  );
}
