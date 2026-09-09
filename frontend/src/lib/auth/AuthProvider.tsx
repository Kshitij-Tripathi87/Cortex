/**
 * Single frontend auth authority (B2 §2). State machine:
 *
 *   UNKNOWN → CHECKING → AUTHENTICATED | ANONYMOUS
 *
 * Boot: no token → ANONYMOUS without any request; token → GET /auth/me →
 * 200 AUTHENTICATED, 401 clear+ANONYMOUS, other failures ANONYMOUS with
 * `error` recorded. Guards render a loader until CHECKING resolves, so
 * protected UI never flashes for anonymous users.
 */

"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { fetchCurrentUser, login as apiLogin, logout as apiLogout, signup as apiSignup } from "@/lib/api/auth";
import { setUnauthorizedHandler } from "@/lib/auth/client";
import { isApiClientError } from "@/lib/auth/errors";
import { clearToken, getToken, setToken, subscribeTokenChanges } from "@/lib/auth/token";
import type {
  AuthOrganization,
  AuthSnapshot,
  AuthStatus,
  AuthUser,
  AuthWorkspace,
  LoginRequest,
  MeResponse,
  SignupRequest,
} from "@/lib/auth/types";

interface AuthContextValue extends AuthSnapshot {
  login: (payload: LoginRequest) => Promise<MeResponse>;
  signup: (payload: SignupRequest) => Promise<MeResponse>;
  logout: () => Promise<void>;
  /** Re-resolve /auth/me. Never throws; returns false when anonymous. */
  refresh: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const PROTECTED_PREFIXES = ["/app", "/workspace", "/onboarding", "/settings"];

function isProtectedPath(pathname: string | null): boolean {
  if (!pathname) return false;
  return PROTECTED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function applySnapshot(data: MeResponse | null, error: string | null): AuthSnapshot {
  if (!data) {
    return { status: "ANONYMOUS", user: null, workspace: null, organization: null, error };
  }
  return {
    status: "AUTHENTICATED",
    user: data.user,
    workspace: data.workspace,
    organization: data.organization,
    error: null,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const router = useRouter();
  const pathname = usePathname();
  const [snapshot, setSnapshot] = useState<AuthSnapshot>({
    status: "UNKNOWN",
    user: null,
    workspace: null,
    organization: null,
    error: null,
  });
  // Guards against repeated 401 bounces from concurrent requests.
  const bouncingRef = useRef(false);
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;

  const invalidate = useCallback(
    (reason: "unauthorized" | "logout" | "boot") => {
      clearToken();
      bouncingRef.current = false;
      setSnapshot({ status: "ANONYMOUS", user: null, workspace: null, organization: null, error: null });
      if (reason === "unauthorized" && isProtectedPath(pathnameRef.current)) {
        const next = encodeURIComponent(pathnameRef.current ?? "/app");
        router.replace(`/auth/login?next=${next}`);
      }
    },
    [router],
  );

  const refresh = useCallback(async (): Promise<boolean> => {
    if (!getToken()) {
      setSnapshot({ status: "ANONYMOUS", user: null, workspace: null, organization: null, error: null });
      return false;
    }
    try {
      const data = await fetchCurrentUser();
      setSnapshot(applySnapshot(data, null));
      return true;
    } catch (error) {
      if (isApiClientError(error) && error.kind === "unauthorized") {
        invalidate("unauthorized");
        return false;
      }
      // Backend unreachable or 5xx: stay logged out but record why.
      setSnapshot({
        status: "ANONYMOUS",
        user: null,
        workspace: null,
        organization: null,
        error: "Cannot reach Nexus right now.",
      });
      return false;
    }
  }, [invalidate]);

  // Boot once.
  useEffect(() => {
    let cancelled = false;
    setSnapshot((prev) => (prev.status === "UNKNOWN" ? { ...prev, status: "CHECKING" } : prev));
    void (async () => {
      if (!getToken()) {
        if (!cancelled) {
          setSnapshot({ status: "ANONYMOUS", user: null, workspace: null, organization: null, error: null });
        }
        return;
      }
      if (!cancelled) await refresh();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- boot exactly once
  }, []);

  // Central 401 hook: any authenticated request that 401s kills the session,
  // except credential-establishing endpoints (filtered in the client).
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (bouncingRef.current) return;
      bouncingRef.current = true;
      invalidate("unauthorized");
    });
    return () => setUnauthorizedHandler(null);
  }, [invalidate]);

  // Another tab logged out → this tab follows immediately.
  useEffect(() => subscribeTokenChanges(() => {
    if (!getToken()) {
      setSnapshot((prev) =>
        prev.status === "ANONYMOUS"
          ? prev
          : { status: "ANONYMOUS", user: null, workspace: null, organization: null, error: null },
      );
    }
  }), []);

  const login = useCallback(async (payload: LoginRequest): Promise<MeResponse> => {
    const tokens = await apiLogin(payload);
    setToken(tokens.access_token);
    bouncingRef.current = false;
    const data = await fetchCurrentUser();
    setSnapshot(applySnapshot(data, null));
    return data;
  }, []);

  const signup = useCallback(async (payload: SignupRequest): Promise<MeResponse> => {
    const tokens = await apiSignup(payload);
    setToken(tokens.access_token);
    bouncingRef.current = false;
    const data = await fetchCurrentUser();
    setSnapshot(applySnapshot(data, null));
    return data;
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await apiLogout();
    } catch {
      // Best effort: local state clears regardless (offline logout works).
    } finally {
      invalidate("logout");
    }
  }, [invalidate]);

  const value = useMemo<AuthContextValue>(
    () => ({ ...snapshot, login, signup, logout, refresh }),
    [snapshot, login, signup, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export type { AuthStatus, AuthUser, AuthWorkspace, AuthOrganization };
