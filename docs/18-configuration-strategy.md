# 18 — Configuration Strategy

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `11-deployment.md` (env vars), `19-operational-policies.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

Cortex has many things to configure — env variables, feature flags, operational
policy versions, security toggles, ML budget knobs, infrastructure sizing. If
**everything is just env vars**, configuration becomes untraceable chaos: a
hot-fix tweaks a number in prod, no one knows why, and replay fails six months
later. Phase 1.5 freezes a **configuration classification** so every knob has
exactly one home, one change mechanism, one validation, and one audit trail.

The frozen rule: **configuration is classified, and the class controls how it
is stored, changed, validated, and observed.** Mixing classes (e.g. using a
feature flag to flip an operational threshold) is forbidden.

## 2. The six configuration classes (frozen)

| Id | Class | Where it lives | Who changes it | Validation | Audit | Reactive? |
|---|---|---|---|---|---|---|
| CF1 | Runtime Config | typed env vars + startup config object | deployment (env reload = new pod) | strict typed at startup; fail-fast | deployment record | no (restart required) |
| CF2 | Feature Flags | flag registry table + admin UI / API | workspace_admin / tenant_admin | schema registry per flag | `feature.set` audit event | yes (per request) |
| CF3 | Policy Config | policy registry (`19-operational-policies.md`) | admin via `policy.publish` | schema-registered + versioned | `policy.published` + replay tests | yes for next operation |
| CF4 | Security Config | secrets manager + RLS-backed tenant policy tables | security on-call / tenant_admin | pinned algorithms; rotation gates | sensitive-action audit | yes (next request) + step-up |
| CF5 | ML Config | `ml_*` config tables + registry | ML operator + admin approval | registry-bound + replay-impact tested | `ml.config.*` audit | yes for next run |
| CF6 | Infrastructure Config | IaC (`infra/terraform`) + cluster overlays | platform admin | plan diff + apply audit | deployment audit | mixed |

Class membership is exclusive. A monitor checks classifications drift; a knob
found in two classes fails CI (`10` §11.1 as part of contract tests).

## 3. Class details

### 3.1 CF1 — Runtime Config

- **Source**: env vars validated by the typed `backend/app/config.py` at startup
  (the closed list from `11-deployment.md` §4). Unknown env vars fail-fast;
  missing required ones fail-fast. No silent defaults.
- **Change**: deployment. Changes require a new pod (rolling deploy / restart);
  no heat-editing. This is intentional — runtime config is **stable** and
  **reproducible** (Constitution Principle 5).
- **Reactivity**: not reactive. Code reads at startup; long-lived objects cache
  values. Workers re-read on next job.
- **Examples**: `CORTEX_DB_DSN`, `CORTEX_GRAPH_MAX_LIVE_DEPTH`,
  `CORTEX_QUERY_TIMEOUT_MS`, `CORTEX_WORKER_CONCURRENCY`,
  `CORTEX_UPLOAD_MAX_BYTES` (the global default; tenant override is CF4 or
  CF2 — see §4 for the resolution rule).
- **Tunable levels**: CF1 leaves the **default** value; CF2/CF4 may override
  per-tenant/per-workspace (see §4). A change to a CF1 default is a deployment
  with a documented ACR if it changes a frozen value.

### 3.2 CF2 — Feature Flags

- **Source**: `iam.feature_flags` registry keyed by
  `(tenant_id, feature_key)` (tenant-scoped by default; workspace-scoped
  variants are allowed only where the contract supports it).
- **Change**: admin via `POST /admin/feature-flags` requires step-up auth
  (`09` §2.3). Emitting `feature.set` is mandatory. Reverting is also
  audited; effects are documented (the toggled behavior, blast radius,
  reason).
- **Validation**: each flag declares `feature_key`, `type`,
  `default_value`, `allowed_values`, `owner_role`, `documentation_link`,
  `introduced_at_version`, `planned_removal_at?`.
- **Reactivity**: per request. Code uses `flags.is_enabled(tenant, key)` only;
  flags are read in-process with a short local cache (≤ 5s) to bound staleness.
  No path may pass a flag value into a deterministic policy computation: a
  flag may *enable/disable* a code path or *select* a published policy version,
  but cannot itself become a policy input (that is CF3).
- **Forbidden combinations**:
  - A flag may not offset a value already covered by CF1, CF3, CF4, or CF5.
  - A flag may not be introduced into hot-path per-request DB queries
    (`13` Constitution Principle 4 — Determinism over hidden heuristics).
- **Decommission**: flags carry `planned_removal_at`; a stale flag (older than
  the planned date) is flagged in the admin UI; expired flags are pruned in a
  scheduled cleanup with a notice.

### 3.3 CF3 — Policy Config

- **Source**: the **policy registry** (`19-operational-policies.md`). Policy
  is versioned content published via `policy.publish` (`05` §12.16), referenced
  by sealed snapshots, signals, recommendations, decisions as `policy_version`.
- **Reactivity**: yes for the *next* operation. A running snapshot uses the
  policy version recorded on it. Promotion of a new policy version does not
  rewrite history; it takes effect on the next snapshot build / next signal
  detection / next recommendation proposal.
- **Validation**: each policy version has a schema version registered in the
  schema registry; publishing is gated by replay-eval goldens (the regression
  corpus, `10` §7.1).
- **Prohibition**: policy never lives as Python literals; thresholds and
  constants inside Python are forbidden. Code may only import policy by
  **reading** the registry at evaluation time. A test asserts no policy
  floats as code constants (`10` §11.1).

### 3.4 CF4 — Security Config

- **Source**: mixes the secrets manager (CF1-equivalent secrets, opaque) and
  tenant-scoped security policy rows in `iam.tenant_security` /
  `iam.workspace_security` (e.g. max upload size per tenant, MFA enforcement,
  retention policy per tenant).
- **Change**: most require step-up auth and a security reviewer for promotion
  beyond the tenant default. Cryptographic algorithms are pinned in code
  (`09` §13); they are **not** configurable per tenant — that would be a
  Phase 1.5 explicit anti-pattern.
- **Reactivity**: yes, per request for tenant-scoped checks; secrets are pulled
  at boot and per remaining lifetime of the running pod.
- **Audit**: every change emits a T5 audit event; sensitive changes emit
  additional `security.config.changed` events reviewed weekly.

### 3.5 CF5 — ML Config

- **Source**: `ml.model_policy_versions`, `ml.compute_budgets`,
  `ml.shadow_modes`. Each is registry-bound; shadow/promotion requires replay
  evidence (`08` §8.4, `08` §12).
- **Change**: ML operator proposes, admin approves. Promotion is gated on
  signed artifacts + evaluation reports (`08` §8.4).
- **Reactivity**: yes for the next run; in-flight runs use the model version
  recorded at start.
- **Audit**: every transition emits `ml.config.*` events; the model whose
  config changed is referenced, plus the experiment artefacts justifying the
  change.

### 3.6 CF6 — Infrastructure Config

- **Source**: `infra/terraform` (portable) with environment-specific overlays
  in `infra/terraform/envs/<env>`. Cluster manifests in `infra/k8s` follow
  the same pattern.
- **Change**: PR review + plan diff + apply. Production apply requires a
  secondary approval. Vendor-specific blocks (cloud provider resources) live
  in thin overlays; never in the portable base.
- **Reactivity**: infra changes are not hot; cluster reconciles via the
  platform.
- **Audit**: deployment audit (`apply` events) and a quarterly review of
  capacity changes vs the capacity plan (`11` §11).

## 4. Class boundary rules

Three rules prevent the chaos AR-001 called out:

### 4.1 Each knob has exactly one home
A configuration variable that affects production behavior must be classified
exactly once. The classification is recorded in a single
`docs/runtime-configuration-catalog.md` (the catalog is generated from code
via a tested contract: each setting declares its class, and the catalog is
checked into the repo). Phase 1 freezes the schema of the catalog; Phase 2
populates it. A drift between catalog and reality fails CI.

### 4.2 Override precedence is fixed
When the same logical setting exists at multiple classes (e.g. global default
in CF1, per-tenant override in CF4, feature flag in CF2), precedence is:

1. CF4 (Security Config) — security always wins.
2. CF5 (ML Config) — used only for ML-bound knobs (does not override non-ML).
3. CF3 (Policy Config) — the deterministic contract in effect.
4. CF2 (Feature Flags) — feature gating only.
5. CF1 (Runtime Config) — base default.
6. CF6 (Infrastructure Config) — sizing that constrains everything else.

A Security override can never be weakened by a feature flag; a feature flag
cannot offset a published policy. The resolution is computed by the central
`config.resolve(setting, scope)` helper, which is the only allowed accessor.
Reach-arounds are forbidden by lint.

### 4.3 Changes are audited and reproducible
- Every CF2/CF3/CF4/CF5 change emits an audit T5 event with the previous and
  new values, the actor, and the rationale (mandatory for CF3 and CF4).
- The catalog is regenerated in CI to reflect the change.
- For CF3 (policy): the change's effect on the regression corpus is part of
  the release gate (`10` §7.1).
- For CF1: the deployment record (commit sha + image digest + config diff)
  is the audit; nothing further is needed.

## 5. Anti-patterns (frozen prohibitions)

- Environment variables used for anything covered by CF2–CF5.
- Feature flags used as thresholds or policy inputs.
- Policy values hard-coded in Python (e.g. `if x < 0.05` where `0.05` is a
  threshold that should be a published policy value).
- Cryptographic algorithms per tenant — security primitives are pinned.
- Secrets in env files or container images (`09` §4.3).
- Storing config in the DB general-store that ought to live in env vars or
  the secrets manager (creates an opaque coupling and a recovery hazard).
- Hot-reloading CF1 by reading env variables mid-process (breaks
  reproducibility); restart is required.

## 6. Validation and exposure

- The `backend/app/config.py` loader is the only constructor of the runtime
  config object; tests assert no other module reads `os.environ` directly
  (`10` §3).
- Feature flags and policy values have a **public representation** in the
  OpenAPI admin group (`/admin/feature-flags`, `/admin/policies`) so the
  audit and administrative UI are identical to the runtime behavior. No
  back-channel config APIs.
- The catalog (`docs/runtime-configuration-catalog.md`) lists every setting:
  name, class, type, default, scope, owner role, change mechanism, audit
  event emitted.

## 7. Frozen decisions summary

- Six exclusive classes (CF1–CF6) with fixed storage, change, validation,
  audit, and reactivity rules.
- Each knob has exactly one home, recorded in a tested catalog.
- Fixed override precedence: CF4 > CF5 > CF3 > CF2 > CF1 > CF6.
- No policy as Python literals; no security primitives per tenant;
  no flags as policy inputs; no hot env reload.
- Every CF2–CF5 change is audited with old/new values, actor, and rationale
  (mandatory for CF3/CF4).
- Frontend never holds config as truth; it reads the admin API.
