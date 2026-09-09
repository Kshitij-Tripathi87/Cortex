/**
 * Token + onboarding-ack storage. Single key, single module.
 *
 * The backend issues stateless Bearer JWTs (60 min, see B1). The frontend
 * stores the token in localStorage and treats ANY 401 from an
 * authenticated request as session death — there is no client-side
 * "is logged in" flag and no parsing of token claims for auth decisions.
 */

const TOKEN_KEY = "cortex:access_token";
const ACK_PREFIX = "cortex:onboarding_ack:";

type Listener = () => void;
const listeners = new Set<Listener>();

function emit(): void {
  for (const fn of listeners) {
    try {
      fn();
    } catch {
      // Listener bugs must never break auth flows.
    }
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
  emit();
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  emit();
}

/** Multi-tab logout sync: a change in another tab notifies this one. */
export function subscribeTokenChanges(fn: Listener): () => void {
  listeners.add(fn);
  const onStorage = (event: StorageEvent) => {
    if (event.key === TOKEN_KEY) fn();
  };
  if (typeof window !== "undefined") {
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(fn);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", onStorage);
    }
  };
}

/** Onboarding acknowledgement is per-user UI progress (B2; server owns identity). */
export function getOnboardingAck(userId: string): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(`${ACK_PREFIX}${userId}`) === "1";
}

export function setOnboardingAck(userId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(`${ACK_PREFIX}${userId}`, "1");
}
