# 07 — Frontend Architecture

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `02-ontology.md`, `04-graph-and-events.md`, `05-api-standards.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose and posture

The Cortex frontend is an **enterprise operational workspace**, not a dashboard.
It supports review-heavy, evidence-driven workflows. Users spend most of their
time inside flows (upload review, conflict triage, evidence inspection, graph
exploration, decision review) — not staring at tiles. The frontend is therefore
information-dense, deterministic in layout, keyboard-navigable, and resilient
to long-running async backend jobs.

The frontend **always consumes backend APIs only**. It never calls models, never
touches the database, never reads object storage directly. All object access is
via short-lived signed URLs issued by the backend.

This document freezes structure and conventions, not pixel-level design.

---

## 2. Technology choices (frozen)

- Next.js **14+** App Router, React 18 Server Components where valuable.
- TypeScript (strict), no `any` outside generated/migration code.
- Styling: Tailwind CSS + a small frozen design-token set (radius, spacing,
  typography, color scales for severity). No CSS-in-JS runtime.
- State: TanStack Query (server cache) + Zustand (UI-local state) + URL state
  for everything that should be sharable (workspace, sort, cursor, filters).
  Redux is not used.
- Forms: React Hook Form + Zod schemas **generated or mirrored** from the
  OpenAPI contracts so client validation matches server validation.
- HTTP client: **generated** from the backend OpenAPI spec (`openapi-typescript`
  + a thin fetcher with auth, idempotency, request-id, and error handler
  injected once). No hand-written API client. A drift gate rejects PRs whose
  client differs from `backend/openapi.json`.
- Visualization: a WebGL-capable canvas renderer for large graphs (e.g.
  `@deck.gl`-style or a custom WebGL layer) and SVG for small graphs;
  deterministic positioning, never random. Charts are read-only.
- Tables: virtualized (`TanStack Virtual` or equivalent) for >500-row views.

### 2.1 No business rules in the frontend
- A rules table belongs to the backend. The frontend renders backend-computed
  results and submits review actions; it never derives supply-chain facts.
- Validation mirrors are for UX only; the server is authoritative and any 422
  is surfaced as an inline error with the server's `details[]`.

---

## 3. Repository layout (within `frontend/`)

```
src/
  app/                  # App Router routes (route-level only)
    (auth)/
    (workspace)/        # workspace-scoped routes (RLS via header)
    (admin)/
    layout.tsx
  features/             # one folder per feature flow (see §4)
    <feature>/
      components/
      hooks/
      schemas/
      store.ts
      api.ts            # only thin generated-client calls
  components/           # cross-feature primitives (Button, Drawer, etc.)
  lib/
    api/                # generated client + fetcher fabric
    auth/
    workspace/
    errors/
    formatting/         # unit/date/money formatting per 02 §3.1
    graph/              # deterministic graph layout helpers
  stores/               # global Zustand stores (workspace switcher, toaster)
  styles/               # tokens + tailwind config
  env/                  # typed env
```

Rules:
- `app/` routes import feature components, never implement business logic.
- `features/<feature>/api.ts` imports only the generated client; it is the only
  feature-internal module allowed to talk HTTP.
- Cross-feature imports go through `components/` primitives or `lib/`, never
  feature-to-feature. This keeps the closed feature set modular.

---

## 4. Feature flows (the operational workspace)

Each feature is a folder under `src/features/` and corresponds to an API group
from `05-api-standards.md` §11. This keeps API surfaces and UI surfaces aligned.

| Feature folder | API group | MVP? |
|---|---|---|
| `auth` | auth | yes |
| `workspaces` | workspaces | yes |
| `uploads` | uploads | yes |
| `evidence` | evidence | yes |
| `claims` | claims | yes |
| `conflicts` | conflicts | yes |
| `reviews` | reviews | yes |
| `entities` | entities | yes |
| `graph` | graph | yes |
| `snapshots` | snapshots | yes |
| `signals` | signals | later |
| `scenarios` | scenarios | later |
| `recommendations` | recommendations | later |
| `decisions` | decisions | later |
| `models` | models | later |
| `admin` | admin | partial |

### 4.1 Workspace shell (MVP)
- Persistent top bar: tenant + workspace switcher, user menu, global command
  palette (`Cmd/Ctrl-K`), notifications bell (job completion, review
  assignment), environment badge.
- Left rail: navigation tree in the frozen order below. Collapsible; state
  persisted per user.
- Main canvas: route content.
- Right rail (contextual): evidence panel — when an object with evidence refs
  is selected, the panel shows evidence + provenance + lineage depth. Always
  present for canonical/graph objects; this is the UI enforcement of
  *evidence first*.
- Status bar (bottom): active snapshot id, readiness state, async jobs in
  progress, optimistic-concurrency version warnings.

### 4.2 Navigation order (frozen)
1. Home (workspace overview: readiness, open reviews, recent snapshots).
2. Uploads.
3. Evidence.
4. Claims & Conflicts (combined inbox).
5. Reviews.
6. Entities (with type sub-nav: Supplier, Warehouse, Plant, Facility, Product,
   Inventory, PurchaseOrder, Shipment, Route, Customer, SalesOrder, Event).
7. Graph Explorer.
8. Snapshots.
9. Signals (later — greyed in MVP).
10. Scenarios (later).
11. Recommendations (later).
12. Decisions (later).
13. Model Center (later; read-only in MVP except admin).
14. Admin (tenants, users, policies, schema registry, audit log).

### 4.3 Upload flow
- A guided stepper: **select source system** → **select file** (drag/drop or
  presigned-upload) → **schema mapping review** → **validation summary** →
  **evidence extraction preview** → **claim extraction summary**.
- Each step surfaces backend job IDs and stays usable while async jobs run.
  Polls `/admin/jobs/{id}` (with exponential backoff) for completion.
- The schema-mapping step shows the auto-mapped columns and allows corrections
  (mapping overrides audited server-side).
- Validation summary shows issues grouped by `issue_type` with counts and a
  downloadable issue CSV.
- Successful uploads transition to a Claims & Conflicts view filtered to that
  upload.

### 4.4 Validation flow
- Lives inside Upload flow and as a standalone re-validation entry per upload.
- Lists `validation_issues` and `conflicts` with severity badges; bulk
  "send to review" action.

### 4.5 Evidence review flow
- Evidence detail page: the supporting bytes (rendered in a viewer by content
  type), the extractor verdict, the locale/timezone context, and the list of
  claims backed by this evidence with their state and decisions.
- "View claim in conflict" deep link arrows the user into the conflict detail.

### 4.6 Conflict review flow
- Inbox of `open` conflicts, sortable by severity and detected_at.
- Per-conflict detail: side-by-side claims, evidence previews, suggestion engine
  that surfaces identity-match strength, an ML candidate banner when one of the
  claims is `ml_candidate` (capped confidence ≤0.5).
- Resolve action opens a structured form: choose claim, rationale (required),
  optional tags. Emits an audited resolution.

### 4.7 Graph exploration flow
- The graph explorer is the operational reasoning surface:
  - **Layout**: deterministic (layered by `facility_type` then by role), no
    physics simulation, no random jitter. Layout config is saved per user.
  - **Pivot on**: node types and edge types multi-select; confidence threshold
    slider (≥0.0..1.0); inferred-only toggle; evidence-required (always true,
    cannot be disabled in MVP).
  - **Selection**: clicking a node opens the right-rail evidence panel and a
    detail drawer with attribute envelopes, current version, lifecycle state,
    lineage (depth ≤3 clickable).
  - **Reach**: "Show impact" runs `GET /graph/impact` and overlays the reach
    subgraph with the deterministic edge-types used.
  - **Temporal**: an as-of slider bound to sealed snapshots; switching to a
    different snapshot re-fetches.
  - **Snapshot binding**: the explorer shows the active `X-Cortex-Snapshot` in
    the status bar and will not silently switch snapshots on the user.
- Rendering:
  - Up to ~10k edges at the default depth uses canvas (WebGL); beyond that
    the explorer enforces server-side reduction via `limit`/`depth` and shows a
    "Load more / Refine filter" affordance rather than rendering blindly.
  - Edges colored by `edge_type`; evidence-required lock icon on edges without
    evidence (cannot occur post-snapshot but can occur in staging read mode).
  - Keyboard: `f` focus, `/` search, `e` expand to evidence, `d` diff to
    previous snapshot, `?` help.

### 4.8 Later-phase pages (placeholders only in MVP)
- Signals page: filterable list with ack/promote-to-event actions and a
  read-only linkage to the operational `Event` node.
- Scenarios page: create from a base snapshot, apply typed overrides, run, compare.
- Recommendations page: inbox with approve/reject; full explanation pane showing
  `rule_id`, `policy_version`, `inputs_hash`, `evidence_refs` (clickable into
  the evidence panel), and `ml_candidate_ref` if used.
- Decisions page: a timeline of `DecisionRecord`s with outcomes; revert (with
  rationale) and observe actions.
- Model center: read-only list of registry entries with promotion/shadow
  toggles gated by admin role.

### 4.9 Model center
- Shows registered models, current/shadow state, calibration drift chart, and
  the synthetic dataset versions each was trained on. Promote/stop actions are
  admin-gated; all changes are surfaced as audit events (`08-ml-platform-strategy.md`).

### 4.10 Decision memory page
- Per-decision timeline; the recorded inputs are hash-anchorable; outcomes are
  shown against expected deltas.

### 4.11 Admin / settings
- Tenants, users/roles, workspace members, policy versions, schema registry,
  audit log search, job monitor, retention configuration, environment info.

---

## 5. State strategy (frozen)

### 5.1 Server cache
- TanStack Query is the only server-state holder. Defaults:
  - `staleTime: 15s` for list reads, `30s` for entity reads, `0` for job status.
  - `gcTime: 5m`. `retry: 1` (the fetcher handles 5xx backoff). Optimistic UI
    is used only for review actions with a known revert patch.
- Query keys are **workspace-scoped** by default: `[workspaceId, group, ...]`.
  Switching workspaces invalidates `['*']` to prevent cross-workspace leakage.

### 5.2 UI-local state
- Zustand stores for: active workspace, command palette, toasters, drawer state,
  graph explorer settings (per user, persisted to `localStorage` keyed by
  tenant+user, not workspace, but only storing layouts, never data).

### 5.3 URL state
- Whatever the user might want to share or bookmark lives in the URL:
  `workspaceId`, route, `sort`, `cursor`, `filters`, `as_of`, `snapshotId`,
  selected graph node id. Pagination cursors are part of the URL too.
- The browser back button must work for in-app navigation; deep links must
  reproduce the same view for the same authorized user.

### 5.4 What the frontend never holds
- No copy of the canonical model beyond what is fetched for current views.
- No policy rules. No derived "facts" computed client-side from data.
- No secrets (no API keys in the browser; only short-lived JWTs).

---

## 6. API integration pattern (frozen)

- A single fetcher fabric in `lib/api/fetcher.ts` injects:
  - `Authorization` (from auth store; refresh handled by a single interceptor
    with a one-flight refresh so concurrent 401s coalesce).
  - `X-Cortex-Workspace` (from active workspace store).
  - `X-Request-ID` (generated; reused across retries).
  - `X-Correlation-ID` (mirrors request id).
  - `Idempotency-Key` for non-GET (generated and stored per logical action;
    retried as the same key).
- The fetcher normalizes the frozen error shape (`05-api-standards.md` §6) and
  surfaces `details[]` to the caller as typed objects.
- Optimistic concurrency uses `If-Match: <version>` from the current cached
  resource; `409 conflict → version_conflict` invalidates the query and prompts
  the user.

---

## 7. Error handling

- A single `<ErrorBoundary>` per route segment renders a friendly, deterministic
  error page with the `request_id`, an action to copy it, and a retry button.
- Form errors: server `details[]` are mapped to fields by `field` name; unknown
  fields appear at the form top as a non-blocking alert with the same shape.
- 401/403 are handled centrally: 401 triggers refresh; persistent 403 shows
  "You do not have access to this workspace" with an offer to switch.
- 429 with `Retry-After` shows a transient banner and pauses retries.

---

## 8. Loading and async states

- All data-bound UI renders one of three skeleton variants (list, detail,
  graph) — never a generic spinner alone. Skeletons are deterministic in size
  to avoid layout shift.
- Async job outcomes are surfaced by polling `/admin/jobs/{id}` with
  exponential backoff (max 30s). A toast + a status bar chip carry the job.
- Snapshot build and long extractions show a deterministic progress bar based
  on `progress` in the job resource; the bar is capped to its last value when
  the job reports no new progress for 60s and shows "Estimating…".

---

## 9. Access control in the UI

- Route guards in `(workspace)/layout.tsx` require an active workspace and a
  role that allows it; otherwise the user is sent to the workspace picker.
- Feature-level role checks render or hide actions (e.g. resolve conflict,
  promote model). The backend is authoritative; UI hiding is convenience only.
- A "read-only mode" toggle is available per user session that disables all
  state-changing actions across the workspace (for auditor/observer roles).

---

## 10. Responsiveness and accessibility

- The workspace is designed for **desktop-first** ≥1280px. Tablet/large-screen
  tablet are supported in read-only/reactive layouts; phones are not a target
  in Phase 2. This avoids over-investing in mobile UX where the operational
  review use case does not live.
- WCAG 2.1 AA conformance is a release gate (`10-testing-and-ci-cd.md`).
- Keyboard navigation is first-class: full command palette, focus rings,
  skip links, and the graph explorer's keyboard map (`§4.7`).

---

## 11. Graph rendering strategy (frozen)

- Renderer choice by edge count:
  - ≤ 500 edges — SVG (DOM interactions cheap).
  - 501–10,000 edges — WebGL (canvas), DOM only for hover tooltips via hit test.
  - > 10,000 — not rendered; the UI demands server-side reduction and shows counts.
- Layout is deterministic by node role (`facility_type`, `entity_type` → band)
  and by edge type; no physics simulation. The same data + same settings must
  produce the same picture (essential for evidence/review screenshots in audits).
- Edge evidence: hovering an edge lists its `evidence_refs` in the right rail;
  clicking drills into the evidence detail page.
- Snapshot binding: the active snapshot id is shown; switching snapshots is an
  explicit user action that resets the view cleanly.

---

## 12. Build, i18n, and theming

- Build via Next.js standalone output; served by Node in the container. Static
  assets served via CDN/fronted by the load balancer in pilot.
- i18n: one locale bundle schema with `en` frozen for MVP; other locales are
  added by translation files only, never by code changes. Date/number/unit
  formatting uses `lib/formatting` per `02-ontology.md` §3.1.
- Theming: a single light theme for MVP. A dark theme is allowed but optional;
  severity colors are fixed and must not be re-mapped, since color carries
  domain meaning (`info/warning/major/critical`).

---

## 13. Frozen decisions summary

- Next.js App Router + TypeScript + TanStack Query + Zustand + Tailwind + WebGL graph.
- No business rules in the browser; OpenAPI-generated client is the only API path.
- Evidence right rail is always present for canonical/graph objects.
- Deterministic graph layout; rendering threshold switches SVG→WebGL→refine.
- URL state for sharable context; workspace query keys enforce isolation on switch.
- Desktop-first; WCAG 2.1 AA gate; no random physics or jitter in the graph.
- All object access through backend-issued signed URLs; no direct storage.

Phase 1 proceeds to `08-ml-platform-strategy.md` on this basis.
