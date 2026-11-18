"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/auth/client";
import { formatMoment } from "@/lib/nexus/overview";
import {
  uploadListSummary,
  uploadName,
  uploadRows,
  uploadStatus,
  type UploadList,
  type UploadTone,
} from "@/lib/nexus/uploads";

const TONE: Record<UploadTone, string> = {
  done: "border-emerald-200 bg-emerald-50 text-emerald-800",
  todo: "border-amber-200 bg-amber-50 text-amber-900",
  blocked: "border-red-200 bg-red-50 text-red-800",
  idle: "border-slate-200 bg-slate-100 text-slate-700",
};

/**
 * Every upload of the workspace with where it stands, each linking to its
 * review page. Before this list an upload could only be reopened by someone
 * who had kept its address.
 */
export function UploadsList({ workspaceId }: { workspaceId: string }): React.JSX.Element {
  const [list, setList] = useState<UploadList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      setList(await apiClient.get<UploadList>("/sources/batches", { workspace_id: workspaceId }));
    } catch (requestError) {
      setList(null);
      setError(requestError instanceof Error ? requestError.message : "The uploads could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert" data-testid="uploads-error">
        The uploads could not be loaded: {error}{" "}
        <button type="button" onClick={() => void load()} className="ml-1 underline">
          Retry
        </button>
      </div>
    );
  }

  if (loading || !list) {
    return <p className="text-sm text-slate-600" data-testid="uploads-loading">Loading your uploads…</p>;
  }

  if (list.batch_count === 0) {
    return (
      <div className="rounded border border-slate-200 bg-white p-6" data-testid="uploads-empty">
        <p className="text-sm font-medium text-slate-900">No uploads yet</p>
        <p className="mt-1 text-sm text-slate-600">
          Upload a CSV or XLSX file. It appears here, and you review it before it becomes part of your data.
        </p>
        <Link href="/upload" className="mt-4 inline-flex rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white">
          Upload source data
        </Link>
      </div>
    );
  }

  return (
    <div data-testid="uploads-list">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-600" data-testid="uploads-summary">{uploadListSummary(list)}</p>
        <Link href="/upload" className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white">
          Upload source data
        </Link>
      </div>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
        {list.batches.map((batch) => {
          const status = uploadStatus(batch);
          const rows = uploadRows(batch);
          const when = formatMoment(batch.uploaded_at);
          return (
            <li key={batch.batch_id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between" data-testid="upload-row">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="break-all text-sm font-medium text-slate-950">{uploadName(batch)}</span>
                  <span className={`rounded border px-2 py-0.5 text-xs font-medium ${TONE[status.tone]}`} data-testid="upload-state">
                    {status.label}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {[when ? `Uploaded ${when}` : null, rows].filter(Boolean).join(" · ")}
                </p>
                {status.detail ? <p className="mt-1 text-sm text-slate-700">{status.detail}</p> : null}
              </div>
              <Link
                href={`/evidence?batch_id=${encodeURIComponent(batch.batch_id)}`}
                className="shrink-0 self-start rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
                aria-label={`${status.action}: ${uploadName(batch)}`}
              >
                {status.action}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
