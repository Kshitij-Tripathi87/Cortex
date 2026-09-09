/**
 * Normalized frontend error model (B2 §8). Every API failure surfaces as an
 * ApiClientError with a safe, mappable message — raw backend payloads and
 * exception strings never reach the UI directly.
 */

export type ApiErrorKind =
  | "unauthorized" // 401 — session invalid; caller must invalidate auth state
  | "forbidden" // 403 — authenticated but not permitted; STAY logged in
  | "conflict" // 409
  | "validation" // 422
  | "rate_limited" // 429
  | "server" // 5xx
  | "network" // unreachable / timeout / CORS
  | "unknown";

export class ApiClientError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly code?: string;
  readonly requestId?: string;
  readonly details?: unknown;

  constructor(
    status: number,
    message: string,
    opts: { code?: string; requestId?: string; details?: unknown } = {},
  ) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.kind = kindForStatus(status);
    this.code = opts.code;
    this.requestId = opts.requestId;
    this.details = opts.details;
  }
}

export function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  if (status === 0) return "network";
  return "unknown";
}

export function isApiClientError(error: unknown): error is ApiClientError {
  return error instanceof ApiClientError;
}

/**
 * Safe UI message for an auth-form failure. Deliberately coarse: credential
 * failures stay generic (no enumeration), rate limits explain the wait,
 * and 5xx/network never leak internals.
 */
export function authFormMessage(error: unknown, action: "login" | "signup"): string {
  if (isApiClientError(error)) {
    switch (error.kind) {
      case "unauthorized":
        return "Invalid email or password.";
      case "conflict":
        return action === "signup"
          ? "An account with this email already exists. Try logging in instead."
          : "This request conflicts with the current state. Please try again.";
      case "validation":
        return typeof error.details === "string" && error.details
          ? error.details
          : "Please check the highlighted fields and try again.";
      case "rate_limited":
        return "Too many attempts. Please wait a little while and try again.";
      case "server":
        return "Something went wrong on our side. Please try again in a moment.";
      case "network":
        return "Cannot reach Nexus. Check your connection and try again.";
      case "forbidden":
        return "You do not have permission to do that.";
      case "unknown":
        return "Something went wrong. Please try again.";
    }
  }
  if (error instanceof Error && error.name === "AbortError") {
    return "The request timed out. Please try again.";
  }
  return "Something went wrong. Please try again.";
}

/** Extract a single readable string from a FastAPI 422 payload, if present. */
export function firstValidationMessage(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown; loc?: unknown };
    if (typeof first?.msg === "string") {
      const loc = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      return loc ? `${loc}: ${first.msg}` : first.msg;
    }
  }
  return null;
}
