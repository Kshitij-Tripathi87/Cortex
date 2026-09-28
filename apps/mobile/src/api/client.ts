/**
 * API client for the Vanessa phone client (Day 25/26).
 *
 * Base URL configured via EXPO_PUBLIC_API_URL / REACT_NATIVE_ENV override
 * (defaults to http://10.0.2.2:8000 — the Android emulator's host alias;
 * on a real device set it to the LAN/production origin).
 *
 * Paths may be either:
 *   - "/devices"                  -> resolved to <base>/api/v1/devices
 *   - "/api/v1/nexus/tasks"       -> resolved as-is
 * The duplicate-prefix bug (e.g. <base>/api/v1/api/v1/...) is prevented
 * by only prepending "/api/v1" when the path does not already include it.
 *
 * Token storage is abstracted (authStore) so the client runs unchanged in
 * Node (contract tests) and on-device (SecureStore).
 */

export const API_BASE_URL =
  process.env.VANESSA_API_URL || "http://10.0.2.2:8000";

export class ApiError extends Error {
  status: number;
  detail: string;
  requestId?: string;

  constructor(status: number, detail: string, requestId?: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

interface FetchOptions {
  params?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
}

function buildUrl(path: string, params?: FetchOptions["params"]): string {
  const fullPath = path.startsWith("/api/") ? path : `/api/v1${path}`;
  const url = new URL(`${API_BASE_URL}${fullPath}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null) continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** The token getter — injected by authStore (SecureStore on device). */
let tokenGetter: () => string | null = () => null;

export function setTokenGetter(getter: () => string | null): void {
  tokenGetter = getter;
}

export async function apiGet<T>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { ...options.headers };
  const token = tokenGetter();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(buildUrl(path, options.params), { headers });
  return handleResponse<T>(resp);
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  options: FetchOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...options.headers,
  };
  const token = tokenGetter();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(buildUrl(path, options.params), {
    method: "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handleResponse<T>(resp);
}

async function handleResponse<T>(resp: Response): Promise<T> {
  const requestId = resp.headers.get("x-request-id") || undefined;
  const text = await resp.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!resp.ok) {
    const detail =
      (body &&
        typeof body === "object" &&
        "detail" in body &&
        String((body as { detail: unknown }).detail)) ||
      `HTTP ${resp.status}`;
    throw new ApiError(resp.status, detail, requestId);
  }
  return body as T;
}

/** Every authoritative response is enveloped as {data: ...}. */
export function unwrap<T>(envelope: { data: T }): T {
  return envelope.data;
}
