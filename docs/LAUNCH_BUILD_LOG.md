# Nexus Launch Build Log — v0.8.5 (Launch Candidate)

Running record of launch slices. Audit baseline: `docs/LAUNCH_GAP_REGISTER.md`
(Days 1–2). Scope freeze: P0 = B1–B10 + golden-path E2E + security/rehearsal/RC
(approved by proceeding default: open signup + trial stub, one workspace/org).

## Slice v0.8.5-B1 — Launch onboarding, backend (Day 3–4, part 1)

**Branch:** `arena/01a08657-cortex` · **Blockers:** B1 (signup/provisioning),
B7 (login/logout/me) — backend half. Frontend auth UI follows in slice B2.

### Shipped

| Area | Change |
|---|---|
| `POST /auth/signup` (201) | Open signup: creates organization + workspace + admin user in one transaction; seeds 7-day trial (`plan=trial`, `trial_ends_at`); global email uniqueness; slug uniquification; per-instance rate limit (30/hr); audit `auth.signup`. |
| `POST /auth/login` | Hardened: inactive-user rejection with uniform 401 (no enumeration oracle), per-email rate limit (20/15min), audit `auth.login`, response extended with `organization_id` (additive). |
| `GET /auth/me` | Principal + workspace + organization + trial state. Gated (`get_current_user`). |
| `POST /auth/logout` | Audit-recorded (`auth.logout`); client discards token (see limitation L1). |
| `POST /auth/change-password` | Current-password check + strength policy; audit `auth.password_changed`. |
| `POST /auth/reset/request` + `/reset/confirm` | Single-use 30-min tokens, hash-only storage, uniform responses (no oracle), token disclosed in-band ONLY in dev/test; pilot/prod delivery via admin CLI until Day-15 email. |
| Password policy | ≥10 chars, letter + digit (server-enforced on signup/change/reset). |
| Migration `015_auth_onboarding` | `core.organizations`; `workspaces.organization_id` (nullable FK); `users.full_name/is_active/password_changed_at`; `password_hash` 128→255; `core.password_resets`. Up + down verified on real PG. |
| `scripts/admin_users.py` | Operator CLI: `issue-reset`, `set-password`, `deactivate`, `activate`, `list`. |
| Tests `test_auth_onboarding.py` | 16 acceptance tests incl. real-JWT cross-workspace 403 on canonical `/nexus/decisions`. |
| Generated artifacts | `backend/openapi.json` + `frontend/src/types/openapi.json` + `api.ts` regenerated (183 paths; also picks up 10 previously-unrecorded `/nexus/models/*`, `/nexus/inference/*` routes). |
| Authz audit | `/signup`, `/reset/request`, `/reset/confirm` classified PUBLIC (note D3i) in test + `docs/architecture/ENDPOINT_AUTHZ_AUDIT.md`. |

### Incidental fixes (found by testing, required for correctness)

1. **`CORTEX_ENV` was silently ignored (critical).** Field `cortex_env` with
   `env_prefix="CORTEX_"` bound to `CORTEX_CORTEX_ENV`, so every deployment —
   including `prod` — ran dev header-identity (complete auth bypass). Fixed by
   renaming the field to `env` (per-field prefix opt-out is unsupported).
   `app/config.py`, `app/infrastructure/security.py`,
   `product/workflo_backend/infrastructure/security.py` updated; k8s
   manifests normalized `production`→`prod` (both spellings still accepted
   defensively). All CI workflows use `test` → non-strict → no CI behavior change.
2. **`AuditEvent.occurred_at` model/migration mismatch.** Model created naive
   `TIMESTAMP` while migration 001 specifies timestamptz and `emit()` passes
   tz-aware datetimes (asyncpg hard-fails). Model now matches the migration.
3. **Migration numbering.** First written as 013 against a stale tree listing;
   the real head was 014 → shipped as `015_auth_onboarding`.

### Verification (this slice)

- 16/16 new tests pass against real PostgreSQL (ephemeral `pgserver`).
- Targeted regressions pass: `test_endpoint_authz_audit`,
  `test_nexus_v082_routing_flip`, `test_dynamic_security_penetration`
  (36 + 19 green in combined runs).
- `ruff check` + `ruff format` clean; `mypy` (strict) clean on changed files.
- `alembic upgrade head` 001→015 + `downgrade -1` + re-`upgrade` verified.
- App boots; `/openapi.json` serves 183 paths incl. all 7 auth routes.
- Remaining gate: CI on the slice PR (full suite + E2E + typecheck incl.
  `openapi-types` drift check).

### Honest limitations (carried, not hidden)

- **L1 — no server-side token revocation.** Stateless HS256 (60 min). Logout
  is client-side + audit. Stolen tokens live until `exp`. Day-11 decision:
  Redis denylist vs. Baroness (documented in `auth.py` module docstring).
- **L2 — rate limits are per-process memory buckets.** Fine at launch scale;
  Redis-backed limiter if multi-instance abuse appears (Day 11).
- **L3 — reset delivery in pilot/prod is admin-assisted** until Day-15 email.
- **L4 — frontend still calls stale auth contract** (`/auth/logout`+`/auth/me`
  now exist; `LoginRequest` shape + pages pending slice B2).

### Next: slice v0.8.5-B2 — Auth UI + route guards

Login/signup pages, auth guard for `/workspace/*` + `/nexus/*`, logout,
`auth.ts` contract alignment, single API base-URL config, session-expiry UX.
