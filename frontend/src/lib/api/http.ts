/**
 * Cortex Nexus — typed HTTP client for backend business APIs (spec §8).
 *
 * No component may call fetch() directly for Nexus APIs; route through the
 * per-domain clients which call this helper. Provides:
 *  - typed responses
 *  - timeout (AbortController)
 *  - normalized domain errors (NexusApiError with status code)
 *  - authentication header injection
 *  - no silent fallback on mutation methods
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

const DEFAULT_TIMEOUT_MS = 15000;

let authToken: string | null = null;

export function setNexusAuthToken(token: string | null) {
  authToken = token;
}

export class NexusApiError extends Error {
  readonly status: number;
  readonly endpoint: string;
  readonly body?: unknown;
  constructor(status: number, endpoint: string, message: string, body?: unknown) {
    super(message);
    this.name = "NexusApiError";
    this.status = status;
    this.endpoint = endpoint;
    this.body = body;
  }
}

export function isNexusApiError(e: unknown): e is NexusApiError {
  return e instanceof NexusApiError;
}

export function isAuthError(e: unknown): boolean {
  return isNexusApiError(e) && (e.status === 401 || e.status === 403);
}

export function isNotFound(e: unknown): boolean {
  return isNexusApiError(e) && e.status === 404;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  query?: Record<string, string | number | undefined | null>;
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const base = path.startsWith("http") ? path : `${API_BASE}${path}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export async function request<T>(opts: RequestOptions): Promise<T> {
  const method = opts.method ?? "GET";
  const url = buildUrl(opts.path, opts.query);
  const controller = new AbortController();
  const timeout = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeout);
  if (opts.signal) {
    // Chain external signal
    if (opts.signal.aborted) controller.abort();
    else opts.signal.addEventListener("abort", () => controller.abort());
  }

  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  try {
    const resp = await fetch(url, {
      method,
      headers,
      body,
      signal: controller.signal,
      cache: "no-store",
    });
    let payload: unknown = undefined;
    const text = await resp.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!resp.ok) {
      const message =
        (payload && typeof payload === "object" && "detail" in payload
          ? String((payload as { detail: unknown }).detail)
          : `HTTP ${resp.status} ${resp.statusText}`) || `HTTP ${resp.status}`;
      throw new NexusApiError(resp.status, opts.path, message, payload);
    }
    return payload as T;
  } catch (e) {
    if (e instanceof NexusApiError) throw e;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new NexusApiError(408, opts.path, "Request timeout");
    }
    // Network / CORS / DNS — normalize to a 0-status error so UI can show "offline".
    throw new NexusApiError(0, opts.path, "Network error: backend unreachable");
  } finally {
    clearTimeout(timer);
  }
}
