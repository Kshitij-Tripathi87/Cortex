/**
 * Post-login redirect validation (B2 §3). `next` is preserved ONLY as a
 * validated internal path — never an arbitrary external URL.
 */

const FALLBACK = "/app";
const MAX_LENGTH = 512;

function isValidInternalPath(value: string): boolean {
  if (!value || value.length > MAX_LENGTH) return false;
  // Must start with exactly one "/" (rejects "//evil", "/\\evil").
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return false;
  // Reject backslashes, whitespace/control chars, and any embedded scheme.
  if (value.includes("\\")) return false;
  if (/[\s<>"'`]/.test(value)) return false;
  // Reject absolute URLs smuggled in (scheme:...), case-insensitive.
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value)) return false;
  // Reject protocol-relative payloads hidden after decoding tricks.
  if (value.includes("//")) return false;
  return true;
}

/**
 * Returns a safe internal redirect target. Accepts raw query values
 * (possibly still encoded) and falls back to `fallback` (default /app).
 */
export function sanitizeNext(raw: string | string[] | null | undefined, fallback = FALLBACK): string {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== "string") return fallback;
  let candidate = value;
  try {
    // Validate the DECODED form so "%2F%2Fevil" cannot slip through.
    candidate = decodeURIComponent(value);
  } catch {
    return fallback;
  }
  // Decode once more to catch double-encoding ("%252F%252Fevil").
  try {
    const double = decodeURIComponent(candidate);
    if (double !== candidate) candidate = double;
  } catch {
    return fallback;
  }
  return isValidInternalPath(candidate) ? candidate : fallback;
}
