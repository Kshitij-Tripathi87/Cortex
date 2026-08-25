# ADR-004: JWT + bcrypt Authentication

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The existing Cortex backend uses header-based dev auth (`X-User-ID`,
`X-Workspace-ID`). The MVP wedge needs real authentication suitable for a
design partner pilot.

## Decision

The MVP uses **bcrypt for password hashing** and **JWT (HS256) for
authentication tokens**. There is no session store, no refresh token, no
OAuth, no Azure AD, no Keycloak.

```
POST /api/v1/auth/login
  { email, password }
  ↓
  verify bcrypt against users.password_hash
  ↓
  JWT issued with claims { user_id, workspace_id, role, exp }
  ↓
  return { token, expires_at }

Subsequent requests:
  Authorization: Bearer <token>
```

## Consequences

**Positive**:
- Stateless auth — no session table, no Redis sessions, no cookie store.
- Single dependency for password hashing (`bcrypt` library, well-maintained).
- JWT validation is pure library code, no network calls.
- Easy to replace with Azure AD / OIDC later by swapping the issuer; the
  `UserPrincipal` claims model is unchanged.

**Negative**:
- No token revocation (logout is client-side discard). Acceptable for MVP;
  full revocation can be added with a token blacklist if needed in Phase 2.
- HS256 means JWT secret must be shared across instances. Acceptable for
  MVP; RS256 + key rotation when enterprise customers demand it.

## Migration Plan

1. New `users` table in `009_mvp_wedge_schema.py` with `password_hash`
   (`String(128)` for bcrypt output).
2. New endpoint `POST /api/v1/auth/login` in `app/api/v1/auth.py`.
3. Update `get_current_user` dependency in `app/modules/identity/dependencies.py`
   to read `Authorization: Bearer <token>` instead of dev headers.
4. Remove (or feature-flag-disable) `HeaderIdentityProvider` from production
   code paths; keep as a test fixture.

## Alternatives Considered

- **Sessions in Redis**: Operational complexity, one more thing to scale.
  Rejected.
- **OAuth / Azure AD**: Not justified for a single design-partner pilot.
  Rejected for MVP.
- **Cookies**: Adds CSRF concerns without benefit for an API-first product.
  Rejected.

## References

- MVP execution plan §10 (security and data handling)
- ADR-007 (workflow engine deferred — same "no over-engineering" principle)
