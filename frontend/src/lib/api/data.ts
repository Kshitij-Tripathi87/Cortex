/**
 * Cortex Nexus — Data Domain API Client.
 */

import { request } from "./http";
import { WorkspaceStateResponse, DatasetMeta } from "@/types/nexus";

export async function fetchDatasets(): Promise<DatasetMeta[]> {
  const data = await request<WorkspaceStateResponse>({ path: "/workspace/state" });
  return (data.datasets_loaded || []).map((d) => ({
    dataset_id: d.name,
    name: d.name,
    row_count: d.row_count ?? 0,
    columns: d.columns ?? [],
    status: "READY",
    completeness_pct: 100.0,
    ingested_at: data.created_at,
  }));
}

export async function ingestRawCsv(
  tableName: string,
  csvContent: string,
  primaryKey?: string
): Promise<unknown> {
  return request({
    method: "POST",
    path: "/workspace/ingest-raw",
    body: {
      table_name: tableName,
      csv_content: csvContent,
      primary_key: primaryKey ?? null,
      max_rows: 10000,
    },
  });
}

export async function uploadCsvFiles(files: File[]): Promise<unknown> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  const base =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
  const resp = await fetch(`${base}/workspace/upload`, {
    method: "POST",
    body: fd,
    cache: "no-store",
  });
  if (!resp.ok) throw new Error(`Upload failed: ${resp.status}`);
  return resp.json();
}
