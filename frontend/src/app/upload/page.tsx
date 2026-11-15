"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { RequireAuth, useAuth } from "@/lib/auth";
import { apiClient } from "@/lib/auth/client";

interface UploadResponse {
  batch_id: string;
  file_id: string;
  status: string;
  checksum: string;
  is_duplicate: boolean;
}

interface CompileResponse {
  batch_id: string;
  claims_created: number;
  conflicts_detected: number;
  blocking_conflicts: number;
  readiness: string;
  explanation: string;
}

interface ReadinessResponse {
  assessment_id: string;
  state: string;
  blocking_conflict_count: number;
  open_conflict_count: number;
  accepted_claim_count: number;
  pending_claim_count: number;
  assumptions: string[];
  explanation: string;
}

interface GraphCompileResponse {
  snapshot_id: string;
  version: number;
  node_count: number;
  edge_count: number;
  integrity_passed: boolean;
}

interface IngestionResult {
  upload: UploadResponse;
  compile?: CompileResponse;
  readiness?: ReadinessResponse;
  graph?: GraphCompileResponse;
}

function UploadForm() {
  const { workspace } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [sourceSystem, setSourceSystem] = useState("unknown");
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<IngestionResult | null>(null);
  const [error, setError] = useState("");
  const router = useRouter();

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || !workspace?.id) {
      setError("Select a file after your workspace has loaded");
      return;
    }

    setProcessing(true);
    setError("");
    setResult(null);

    const formData = new FormData();
    formData.append("workspace_id", workspace.id);
    formData.append("file", file);
    formData.append("source_system_hint", sourceSystem);

    try {
      const upload = await apiClient.post<UploadResponse>("/sources/upload", formData);
      setResult({ upload });

      const query = { workspace_id: workspace.id };
      const compile = await apiClient.post<CompileResponse>(
        `/sources/batches/${encodeURIComponent(upload.batch_id)}/compile`,
        undefined,
        { query },
      );
      setResult({ upload, compile });

      const readiness = await apiClient.post<ReadinessResponse>(
        `/readiness/batches/${encodeURIComponent(upload.batch_id)}`,
        undefined,
        { query },
      );
      setResult({ upload, compile, readiness });

      if (["ready", "ready_with_assumptions"].includes(readiness.state.toLowerCase())) {
        const graph = await apiClient.post<GraphCompileResponse>(
          `/graph/batches/${encodeURIComponent(upload.batch_id)}/compile`,
          undefined,
          { query },
        );
        setResult({ upload, compile, readiness, graph });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingestion validation failed");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#0a0a0b] p-8 font-mono text-xs text-[#e5e5e5]">
      <div className="mx-auto max-w-3xl">
        <header className="mb-8 border-b border-[#26262b] pb-5">
          <p className="text-[9px] uppercase tracking-widest text-[#06b6d4]">Cortex data foundation</p>
          <h1 className="mt-2 text-2xl font-bold tracking-widest text-white">CONNECT BUSINESS DATA</h1>
          <p className="mt-2 text-[#9ca3af]">
            Upload a source file, compile claims, assess readiness, and build the workspace graph.
          </p>
          <p className="mt-3 text-[10px] text-[#6b7280]">Workspace: {workspace?.name ?? "Loading workspace…"}</p>
        </header>

        <form onSubmit={handleSubmit} className="space-y-5 border border-[#26262b] bg-[#0f0f11] p-5">
          <div>
            <label htmlFor="source-system" className="mb-2 block text-[10px] uppercase tracking-widest text-[#9ca3af]">Source system</label>
            <select
              id="source-system"
              value={sourceSystem}
              onChange={(event) => setSourceSystem(event.target.value)}
              className="w-full border border-[#26262b] bg-[#0a0a0b] px-3 py-2 text-white"
            >
              <option value="unknown">Unknown</option>
              <option value="erp">ERP</option>
              <option value="wms">WMS</option>
              <option value="tms">TMS</option>
              <option value="spreadsheet">Spreadsheet</option>
              <option value="manual">Manual</option>
            </select>
          </div>
          <div>
            <label htmlFor="source-file" className="mb-2 block text-[10px] uppercase tracking-widest text-[#9ca3af]">CSV or XLSX file</label>
            <input
              id="source-file"
              type="file"
              accept=".csv,.xlsx"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="w-full border border-[#26262b] bg-[#0a0a0b] px-3 py-2 text-[#9ca3af]"
              required
            />
          </div>
          <button
            type="submit"
            disabled={processing || !workspace?.id}
            className="border border-[#06b6d4] bg-[#064e5b] px-5 py-2 text-[10px] uppercase tracking-widest text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {processing ? "Validating and building context…" : "Upload and validate"}
          </button>
        </form>

        {error && <div className="mt-5 border border-[#e5484d]/50 bg-[#e5484d]/10 p-4 text-[#fca5a5]">{error}</div>}

        {result && (
          <section className="mt-5 space-y-4 border border-[#26262b] bg-[#0f0f11] p-5">
            <div>
              <h2 className="text-sm font-bold uppercase tracking-widest text-white">Ingestion result</h2>
              <p className="mt-1 break-all text-[10px] text-[#6b7280]">Batch {result.upload.batch_id} · checksum {result.upload.checksum}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <StatusCard label="Upload" value={result.upload.status} />
              <StatusCard label="Readiness" value={result.readiness?.state ?? "PROCESSING"} />
              <StatusCard label="World State" value={result.graph ? `v${result.graph.version}` : "NOT BUILT"} />
            </div>
            {result.compile && (
              <p className="text-[10px] text-[#9ca3af]">
                {result.compile.claims_created} claims · {result.compile.conflicts_detected} conflicts · {result.compile.blocking_conflicts} blocking
              </p>
            )}
            {result.readiness && (
              <div className="border-l-2 border-[#06b6d4] pl-3 text-[10px] text-[#9ca3af]">
                {result.readiness.explanation}
              </div>
            )}
            {result.graph && (
              <p className="text-[10px] text-[#86efac]">
                Authoritative graph built: {result.graph.node_count} nodes, {result.graph.edge_count} edges.
              </p>
            )}
            <div className="flex flex-wrap gap-4 pt-2">
              <button onClick={() => router.push("/nexus/cockpit")} className="text-[10px] uppercase tracking-widest text-[#06b6d4] hover:text-white">Open cockpit →</button>
              <button onClick={() => router.push("/nexus/decision-room")} className="text-[10px] uppercase tracking-widest text-[#06b6d4] hover:text-white">Open Decision Room →</button>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-[#26262b] bg-[#0a0a0b] p-3">
      <div className="text-[9px] uppercase tracking-widest text-[#6b7280]">{label}</div>
      <div className="mt-2 break-words text-white">{value}</div>
    </div>
  );
}

export default function UploadPage() {
  return (
    <RequireAuth>
      <UploadForm />
    </RequireAuth>
  );
}
