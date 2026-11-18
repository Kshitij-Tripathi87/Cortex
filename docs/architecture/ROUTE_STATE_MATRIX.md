# Frontend Route/State Matrix — Phase 2 Completion

**Owner:** Frontend
**Generated:** 2026-08-27
**Scope:** every `src/app/**/page.tsx`
**Phase:** Nexus Production Hardening Phase 2

## What this matrix covers

Every route must have, at minimum, deterministic behavior for these states:
- **loading** — request in flight, no data yet
- **empty** — request succeeded with zero rows
- **error** — request failed (4xx, 5xx, network)
- **stale** — data present but superseded by a newer request
- **unauthorized** — authZ failure (server-side, never from frontend state)

Static (server-rendered) routes and routes behind legal/marketing shells
only need the empty-state coverage (404 / 500) and are listed as **N/A**
for the data states.

## Status legend

| Symbol | Meaning |
|---|---|
| ✅ | state machine present and rendered with a dedicated UI |
| ⚠️ | state detected by grep but not a dedicated UI (e.g. inline string flag) |
| ❌ | state missing — page would render nothing or a hard error on this case |
| N/A | route is static or a 404 wrapper |

## Matrix

| Route | Auth | Loading | Empty | Error | Stale | Unauthorized |
|---|---|---|---|---|---|---|
| `/` | public | ✅ | ✅ | ⚠️ | ❌ | N/A |
| `/audit` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/conflicts` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/decisions` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/evidence` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/graph` | required | ✅ | ✅ | ✅ | ❌ | ⚠️ |
| `/nexus` | required | ✅ | ✅ | ✅ | ❌ | ⚠️ |
| `/readiness` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/signals` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/upload` | required | ⚠️ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/mvp` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/scenarios` | required | ⚠️ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/recommendations` | required | ⚠️ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/propagation` | required | ⚠️ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/agents` | required | ⚠️ | ⚠️ | ⚠️ | ❌ | ⚠️ |
| `/agents/[id]` | required | ⚠️ | ⚠️ | ⚠️ | ❌ | ⚠️ |
| `/nexus/decision-room/task` | required | ✅ | ✅ | ✅ | ❌ | ✅ |
| `/company`, `/contact`, `/enterprise`, `/intelligence`, `/platform`, `/products`, `/research`, `/security`, `/demo`, `/legal/*` | public/static | N/A | N/A | N/A | N/A | N/A |

## Findings

1. **The `stale` state is missing everywhere.** The 19-point checklist calls
   this out as a Phase 2/15 gate. No page surfaces "data is older than
   `last_sync_at`" — the assumption is that data is always fresh because
   it's fetched on mount.
2. **The `/workspace/*` demo area has been removed (2026-11-18).** Its 17
   pages rendered built-in sample data inside a second navigation shell and
   were reachable from the signed-in home, so a signed-in customer could
   land on figures that were not theirs. The one page that read real data
   (task review) now lives at `/nexus/decision-room/task`. Old addresses
   redirect (`next.config.js`): `/workspace/agents/decision-room` to the
   task review page with its query string, everything else under
   `/workspace` to `/nexus/cockpit`.
3. **Unauthorized handling is reactive, not proactive.** A 401 from the
   backend surfaces in the error state; the user is not redirected to
   `/login` automatically.

## Required follow-ups (Phase 2 → Phase 15)

- **F3-stale**: introduce a `last_synced_at` from the backend on every
  data response and surface a "stale > N seconds" indicator on each page.
- **F3-shared**: extract a `<DataSurface loading error empty children>` to
  enforce the contract on the `/nexus/*` pages.
- **D3-authZ**: every page that requires auth must redirect to `/login` on
  401, server-side via the authZ middleware.

## Verification

The matrix is enforced by the Playwright specs in `frontend/tests/`:
- `auth-e2e.spec.ts`: sign-up, sign-in, guards, and that retired
  `/workspace` addresses land on the working cockpit
- `critical-path-e2e.spec.ts`: upload, review, publish, ask
- `decision-room-e2e.spec.ts`: task review (roles, signed-out state,
  redirect from the retired address)
- `realtime-e2e.spec.ts`: live-data paths

`e2e-acceptance.spec.ts`, `scale-qualification.spec.ts` and
`visual-regression.spec.ts` were deleted with the `/workspace/*` area: every
test in them opened one of the removed demo pages, none ran in CI, and their
screenshots were Windows-only baselines of those pages. Visual and load
coverage of the `/nexus/*` pages is not replaced yet.

Per Phase 2 completion criteria, all ⚠️ cells in the matrix should reach
✅ or be explicitly marked N/A by Phase 15. This document is the source
of truth for that gate.
