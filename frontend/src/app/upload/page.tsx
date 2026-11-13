"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { apiClient, useAuth } from "@/lib/auth";

interface SourceUploadResponse {
  batch_id: string;
  file_id: string;
  status: string;
  checksum: string;
  is_duplicate: boolean;
  profiling_scheduled: boolean;
}

export default function UploadPage() {
  const { status, workspace } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [sourceSystem, setSourceSystem] = useState("unknown");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<SourceUploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("Select a CSV or XLSX source file.");
      return;
    }
    if (!workspace?.id) {
      setError("Your account does not have an active workspace.");
      return;
    }

    setUploading(true);
    setError(null);
    setResult(null);

    const formData = new FormData();
    formData.append("workspace_id", workspace.id);
    formData.append("file", file);
    formData.append("source_system_hint", sourceSystem);

    try {
      // apiClient supplies the authenticated Bearer token and preserves the
      // browser-generated multipart boundary for FastAPI's UploadFile parser.
      const response = await apiClient.post<SourceUploadResponse>(
        "/sources/upload",
        formData,
      );
      setResult(response);
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "Source upload failed. Check the connection and try again.",
      );
    } finally {
      setUploading(false);
    }
  };

  if (status === "UNKNOWN" || status === "CHECKING") {
    return (
      <div className="flex min-h-[60vh] items-center justify-center px-6">
        <p className="text-sm text-ink-secondary">Checking your Cortex session…</p>
      </div>
    );
  }

  if (status !== "AUTHENTICATED") {
    return (
      <div className="flex min-h-[60vh] items-center justify-center px-6 text-center">
        <div className="max-w-md">
          <h1 className="text-xl font-semibold text-ink">Sign in to upload data</h1>
          <p className="mt-2 text-sm text-ink-secondary">
            Source files are uploaded into your authenticated workspace.
          </p>
          <Link
            href="/auth/login?next=%2Fupload"
            className="button-primary mt-5 inline-flex"
          >
            Sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-w-0">
      <header className="flex min-h-16 flex-wrap items-center justify-between gap-4 border-b border-border px-5 py-3 sm:px-8">
        <div>
          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            <Link href="/nexus/cockpit" className="font-semibold text-ink hover:text-accent">
              Cortex Nexus
            </Link>
            <span>/</span>
            <span>Source intake</span>
          </div>
          <p className="mt-1 text-[11px] text-ink-secondary">
            Upload operational data into the active workspace
          </p>
        </div>
        <Link href="/nexus/world" className="button-secondary">
          World State Explorer
        </Link>
      </header>

      <main className="px-5 py-8 sm:px-8">
        <section className="max-w-2xl border border-border bg-surface">
          <div className="border-b border-border px-5 py-4">
            <p className="eyebrow">Operational data intake</p>
            <h1 className="mt-2 text-xl font-semibold tracking-tight text-ink">
              Upload a source file
            </h1>
            <p className="mt-1 text-sm text-ink-secondary">
              Supported formats: CSV and XLSX. The source is validated, stored and profiled
              before downstream evidence review and graph compilation.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5 px-5 py-5">
            <div className="border border-border bg-surface-2 px-4 py-3">
              <p className="eyebrow">Authenticated workspace</p>
              <p className="mt-1 text-sm font-medium text-ink">{workspace?.name ?? "Active workspace"}</p>
              <p className="mt-1 break-all font-mono text-[10px] text-ink-muted">
                {workspace?.id ?? "Workspace unavailable"}
              </p>
            </div>

            <div>
              <label htmlFor="source-system" className="mb-2 block text-xs font-medium text-ink">
                Source system
              </label>
              <select
                id="source-system"
                value={sourceSystem}
                onChange={(event) => setSourceSystem(event.target.value)}
                className="field w-full"
                disabled={uploading}
              >
                <option value="unknown">Unknown / spreadsheet</option>
                <option value="erp">ERP</option>
                <option value="wms">WMS</option>
                <option value="tms">TMS</option>
                <option value="oms">OMS</option>
                <option value="mes">MES</option>
                <option value="scm_planning">SCM planning</option>
                <option value="manual">Manual</option>
              </select>
            </div>

            <div>
              <label htmlFor="source-file" className="mb-2 block text-xs font-medium text-ink">
                Source file
              </label>
              <input
                id="source-file"
                type="file"
                accept=".csv,.xlsx"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                className="field w-full"
                disabled={uploading}
                required
              />
              {file && (
                <p className="mt-2 text-[11px] text-ink-secondary">
                  {file.name} · {(file.size / 1024).toFixed(1)} KB
                </p>
              )}
            </div>

            {error && (
              <div
                className="border border-critical/40 bg-critical-subtle px-4 py-3 text-sm text-critical"
                role="alert"
              >
                {error}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={uploading || !file || !workspace?.id}
                className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {uploading ? "Uploading…" : "Upload source"}
              </button>
              <span className="text-[11px] text-ink-muted">
                Workspace scope and identity are supplied by your active session.
              </span>
            </div>
          </form>
        </section>

        {result && (
          <section className="mt-5 max-w-2xl border border-border bg-surface" aria-live="polite">
            <div className="border-b border-border px-5 py-4">
              <p className="eyebrow">Upload accepted</p>
              <h2 className="mt-1 text-base font-semibold text-ink">
                Source file stored
              </h2>
              <p className="mt-1 text-xs text-ink-secondary">
                This confirms source intake only. Evidence review and graph compilation are
                separate downstream steps; the World State is not claimed to be updated yet.
              </p>
            </div>
            <dl className="grid gap-3 px-5 py-4 sm:grid-cols-2">
              <div>
                <dt className="eyebrow">Batch ID</dt>
                <dd className="mt-1 break-all font-mono text-xs text-ink">{result.batch_id}</dd>
              </div>
              <div>
                <dt className="eyebrow">File ID</dt>
                <dd className="mt-1 break-all font-mono text-xs text-ink">{result.file_id}</dd>
              </div>
              <div>
                <dt className="eyebrow">Status</dt>
                <dd className="mt-1 text-xs text-ink">{result.status}</dd>
              </div>
              <div>
                <dt className="eyebrow">Profiling</dt>
                <dd className="mt-1 text-xs text-ink">
                  {result.profiling_scheduled ? "Scheduled" : "Not scheduled"}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="eyebrow">SHA-256 checksum</dt>
                <dd className="mt-1 break-all font-mono text-[10px] text-ink-muted">
                  {result.checksum}
                </dd>
              </div>
            </dl>
            <div className="flex flex-wrap gap-3 border-t border-border px-5 py-4">
              <Link href="/nexus/world" className="button-secondary">
                Inspect World State
              </Link>
              <Link href="/nexus/operations" className="button-secondary">
                Operations
              </Link>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
