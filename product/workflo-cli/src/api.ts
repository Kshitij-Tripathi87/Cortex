import { loadConfig, WorkfloConfig } from "./config";

export interface SandboxRecord {
  id: string;
  workspace_id: string;
  name: string;
  status: string;
  policy: Record<string, unknown>;
  layout?: string[];
}

export interface RunRecord {
  id: string;
  status: string;
  sandbox_id?: string;
  plan?: { steps: Array<{ action: string; detail: string }> };
  findings?: Array<{ severity: string; title: string; evidence: string; suggestion: string }>;
  events?: Array<{ seq: number; type: string; message: string }>;
  artifacts?: Array<{ name: string; path: string; size_bytes: number }>;
  execution?: {
    exit_code: number | null;
    stdout: string;
    stderr: string;
    duration_ms: number;
    timed_out: boolean;
  };
}

async function request<T>(
  config: WorkfloConfig,
  method: string,
  pathName: string,
  body?: unknown,
): Promise<{ status: number; data: T }> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (config.token) headers["Authorization"] = `Bearer ${config.token}`;

  const response = await fetch(`${config.api_url}${pathName}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  return { status: response.status, data: data as T };
}

export async function probeHealth(config: WorkfloConfig): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    const response = await fetch(`${config.api_url}/api/v1/workflo/health`, {
      signal: controller.signal,
    });
    clearTimeout(timer);
    return response.ok;
  } catch {
    return false;
  }
}

export const api = {
  health: (c: WorkfloConfig) => request(c, "GET", "/api/v1/workflo/health"),
  createSandbox: (c: WorkfloConfig, body: object) =>
    request<SandboxRecord>(c, "POST", "/api/v1/workflo/sandboxes", body),
  inspectSandbox: (c: WorkfloConfig, id: string) =>
    request<Record<string, unknown>>(c, "GET", `/api/v1/workflo/sandboxes/${id}`),
  destroySandbox: (c: WorkfloConfig, id: string) =>
    request(c, "DELETE", `/api/v1/workflo/sandboxes/${id}`),
  writeSandboxFile: (c: WorkfloConfig, id: string, p: string, contentBase64: string) =>
    request(c, "POST", `/api/v1/workflo/sandboxes/${id}/files`, {
      path: p,
      content_base64: contentBase64,
    }),
  listSandboxFiles: (c: WorkfloConfig, id: string) =>
    request<{ files: Array<{ path: string }> }>(
      c,
      "GET",
      `/api/v1/workflo/sandboxes/${id}/files`,
    ),
  execInSandbox: (
    c: WorkfloConfig,
    id: string,
    command: string,
    timeout_s?: number,
  ) =>
    request(c, "POST", `/api/v1/workflo/sandboxes/${id}/execute`, {
      command,
      timeout_s,
    }),
  createRun: (c: WorkfloConfig, body: object) =>
    request<RunRecord>(c, "POST", "/api/v1/workflo/runs", body),
  getRun: (c: WorkfloConfig, id: string) =>
    request<RunRecord>(c, "GET", `/api/v1/workflo/runs/${id}`),
  runArtifacts: (c: WorkfloConfig, id: string) =>
    request<{ artifacts: Array<{ name: string; path: string; size_bytes: number }> }>(
      c,
      "GET",
      `/api/v1/workflo/runs/${id}/artifacts`,
    ),
  agentPlan: (c: WorkfloConfig, intent: string, fileIndex: string[]) =>
    request(c, "POST", "/api/v1/workflo/agent/plan", {
      intent,
      file_index: fileIndex,
    }),
};

export async function streamRunEvents(
  config: WorkfloConfig,
  runId: string,
  onEvent: (type: string, message: string, data: Record<string, unknown>) => void,
): Promise<void> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (config.token) headers["Authorization"] = `Bearer ${config.token}`;
  const response = await fetch(
    `${config.api_url}/api/v1/workflo/runs/${runId}/events`,
    { headers },
  );
  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let dataLine = "";
      for (const lineText of block.split("\n")) {
        if (lineText.startsWith("event: ")) currentEvent = lineText.slice(7).trim();
        else if (lineText.startsWith("data: ")) dataLine += lineText.slice(6);
      }
      if (dataLine) {
        try {
          const parsed = JSON.parse(dataLine);
          onEvent(currentEvent, parsed.message ?? "", parsed.data ?? {});
        } catch {
          onEvent(currentEvent, dataLine, {});
        }
      }
    }
  }
}
