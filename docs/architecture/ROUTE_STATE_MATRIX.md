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
| `/audit` | redirects to `/nexus/operations#audit` (finding 9) | N/A | N/A | N/A | N/A | N/A |
| `/conflicts` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/decisions` | required | ✅ | ⚠️ | ✅ | ❌ | ⚠️ |
| `/evidence` | required | ✅ | ✅ | ✅ | ❌ | ⚠️ |
| `/nexus/cockpit` | required | ✅ | ✅ | ✅ | ❌ | ⚠️ |
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
4. **The Command Center reads the published records (2026-11-18).** Its
   figures used to come from the risk register alone, which only a direct
   API call writes, so a workspace with late purchase orders showed "0 open
   disruptions", "World state: Not available" and "Data posture:
   Incomplete" beside an Ask box that listed the late orders. The page now
   calls `GET /nexus/workspace/overview`, which the server derives from the
   records with the code that also answers the Ask box (late orders, stock
   below its threshold, partners flagged by their own status, record and
   relationship totals, published version). A figure that could not be
   checked is a dash with the reason, not a zero; a failed read says so.
   Recorded risks are still listed, labelled as what they are.
5. **`/evidence` without a batch lists the uploads (2026-11-18).** It used
   to say "Open this page from a source upload so the batch ID is
   included", so an upload could only be reopened by someone who had kept
   its address. `GET /sources/batches` returns the uploads of the
   workspace, newest first, with their files and state; `/upload` links to
   the list.
6. **The `/nexus` pages fit a phone (2026-11-18).** The shell was one row at
   every width, so below 1024 px the navigation strip sat beside the page
   and pushed it off screen (the pages measured 889 to 1128 px wide on a
   390 px screen). The shell is now a column below `lg`: the six sections
   wrap above the page, none behind a sideways scroll. On `/evidence` the
   claims table scrolls inside its own box. Measured with data at 390, 768
   and 1280 px: every signed-in page is exactly as wide as the screen.
7. **`/security` states what exists (2026-11-18).** It promised single
   sign-on, mutual TLS, AES-256 with customer-managed keys, dedicated
   infrastructure per customer and a tamper-evident log exported to
   monitoring tools; none of these exist. Each sentence now describes
   behaviour in the code (the sources are listed at the top of
   `src/app/security/page.tsx`), and what is missing is listed under "Not
   available yet". Where data is hosted, disk encryption and backups are
   properties of a deployment that the repository cannot show: the page
   says so and must be completed by whoever runs the deployment.

8. **A page must fit a phone with any font (2026-11-18).** `/nexus/operations`
   was exactly 390px wide on one machine and 416px in CI: a health key such
   as `worker.heartbeat.last_sweep_published` cannot wrap, and it sat in a
   grid that named its columns only from `lg` up. Below that breakpoint such
   a grid has one implicit column, which cannot be narrower than its content,
   so the widest unbreakable word decides the width of the page. All thirty
   grids of that kind now carry `grid-cols-1` (a column that can shrink);
   long keys wrap; the data-quality table scrolls inside its card; the
   `/app` header wraps. The phone tests measure every page twice, as rendered
   and with the text made wider than any installed font, on an empty
   workspace and on one with data. With the old Operations page that second
   measurement fails on any machine.
9. **`/audit` was removed; the log is on Operations (2026-11-18).** The page
   sent no sign-in, so it could not load anything once sign-in is enforced;
   it read the workspace from the address or used `default-workspace`; and
   its category and date filters were sent to an API that has neither. No
   page linked to it. The Operations page shows the log, now beyond the
   first hundred events ("Show older events"), and a feed that failed is
   reported as not loaded instead of as "no events recorded". Model health
   lists one line per kind of prediction instead of thirty rows of `null`,
   and the API no longer reports an accuracy nobody measured.

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
- `critical-path-e2e.spec.ts`: upload, review, publish, ask; the list of
  uploads; the Command Center figures against the uploaded rows and the
  Ask box, for an empty workspace and for a failed read; every `/nexus` page at
  390 px (navigation above the page, nothing to scroll sideways)
- `decision-room-e2e.spec.ts`: task review (roles, signed-out state,
  redirect from the retired address)
- `realtime-e2e.spec.ts`: live-data paths
- `public-forms-e2e.spec.ts`: the demo and contact forms; that `/security`
  no longer makes the promises listed in finding 7

`e2e-acceptance.spec.ts`, `scale-qualification.spec.ts` and
`visual-regression.spec.ts` were deleted with the `/workspace/*` area: every
test in them opened one of the removed demo pages, none ran in CI, and their
screenshots were Windows-only baselines of those pages. Visual and load
coverage of the `/nexus/*` pages is not replaced yet.

Per Phase 2 completion criteria, all ⚠️ cells in the matrix should reach
✅ or be explicitly marked N/A by Phase 15. This document is the source
of truth for that gate.
