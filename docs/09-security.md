# 09 — Security Baseline

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `04-graph-and-events.md`, `05-api-standards.md`, `06-database-strategy.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Posture

Cortex holds enterprise supply-chain evidence. The baseline is **enterprise-
grade and zero-trust inside the boundary**: every request is authenticated and
authorized, every workspace is isolated at the storage layer, every audit
record is tamper-evident, and every untrusted input is treated as hostile
until validated.

This document freezes the security controls for Phase 1. It is intended to be
practical (implementation can follow it directly) and enterprise in tone.

---

## 2. Identity, authentication, authorization

### 2.1 Authentication
- OIDC-based authentication is the default; local password auth is available
  for development only and never enabled in pilot/production.
- Bearer access tokens are RS256 JWTs, ≤15-min TTL. Refresh tokens are
  rotating, ≥90-day sliding window, revocable via a server-side denylist; token
  theft detection raises `auth.refresh_reused` and rotates the device key.
- Service-to-service auth: short-lived workload-identity tokens (mTLS bootstrap
  with internal CA in pilot; SPIFFE-style IDs for production phases). No
  long-lived API keys for service traffic.
- API keys, where allowed (admin only, narrow scope), are hashed at rest with
  Argon2id and rotated on a configurable schedule; revocation is immediate.
- MFA is required for all admin and decision-approvers (TOTP or WebAuthn).
  Long-running sessions require step-up auth before promoting a model, approving
  a recommendation, or merging entities.

### 2.2 Authorization
- RBAC with the closed role set:
  `tenant_admin`, `workspace_admin`, `analyst`, `reviewer`,
  `decision_maker`, `auditor`, `ml_operator`, `viewer`, `guest`.
- Roles are scoped per workspace; a user with a role in workspace A has no
  implicit role in workspace B. Membership lives in `iam.memberships`.
- Permissions are enforced **at the API layer** (route guards), **at the
  service layer** (action policies), and **at the data layer** (RLS — see
  `06-database-strategy.md` §5). Defense in depth: no single enforcement point
  is trusted alone.
- A permission matrix maps role → action; changing the matrix is an ACR.
- Deny by default: any action without an explicit grant is forbidden and
  returns `403 forbidden`.

### 2.3 Step-up and sensitive actions
Sensitive actions additionally require step-up auth within the last 5 minutes:
- `decision.approve` (any recommendation), `entity.merge`, `entity.split`,
- `ml.model.promote`/`rollback`, `policy.publish`, `workspace.member.role_change`,
- `audit.export`.

---

## 3. Workspace and tenant isolation

### 3.1 Tenant isolation (physical, at the data layer)
- Each tenant occupies its own physical schema-partition set and its own
  object-storage prefix root
  (`tenants/{tenant_id}/...`). RLS enforces tenant id (`06-database-strategy.md`).
- A tenant cannot query another tenant's rows, including via joins. RLS is set
  on every tenant-scoped table; cross-tenant tests are a release gate.
- Object storage access is gated by the backend, which validates the tenant_id
  on the RLS-authenticated user before issuing any signed URL; the URL's key
  path includes the tenant_id and is verified at signing time.

### 3.2 Workspace isolation (logical, within a tenant)
- Workspace id is required on every workspace-data request (`05-api-standards.md`
  §5.2) and propagated as `app.workspace_id` connection-level GUC for RLS.
- Cross-workspace data is forbidden by default; the only cross-workspace reads
  are the shared party directory and admin/audit views, each gated by a
  designated role.

### 3.3 Cross-tenant/workspace leakage protections in the app
- Query keys are workspace-scoped; switching workspaces invalidates the
  in-memory cache (`07-frontend-architecture.md` §5.3) to prevent user-facing
  leakage between workspaces.
- Logs must never print PII, but also must never print rows from a different
  tenant than the request's. OpenTelemetry attributes are tenant+workspace
  id only, never row contents.

---

## 4. Encrypted storage and secrets

### 4.1 At rest
- Postgres: TDE via cloud provider or LUKS at the volume layer for
  self-managed pilot. Column-level encryption for designated sensitive fields
  (tax ids, contact PII) using envelope encryption with a per-tenant DEK.
- Object storage: server-side encryption with a per-tenant KMS key
  (S3 SSE-KMS or MinIO KMS equivalent). Object keys include tenant id; the
  backend validates tenant match before issuing any signed URL.
- Backups are encrypted with separate keys from live data and never stored in
  the same KMS hierarchy as the live database.

### 4.2 In transit
- TLS 1.3 only, HSTS preload, certificate rotation ≤30d; mTLS for
  service-to-service traffic inside the VPC.
- No plaintext internal ports reachable outside the trust boundary. Health
  endpoints are unauthenticated but reveal only boolean status.

### 4.3 Secrets
- No secrets in repo, env files, container images, or frontend bundles.
- Secrets live in a secrets manager (cloud-native or Vault for self-managed);
  the app pulls at boot; workers pull per job. Rotation policy per secret;
  every secret has an owner and a rotation deadline trackd in the admin UI.
- Prohibited tokens are detected by pre-commit and CI scan
  (git-history secrets scan, trufflehog equivalent).

---

## 5. Immutable uploads

- Upload objects are stored under an **object-lock** (legal-hold/WORM) for the
  tenant-configured retention period after they are validated. This implements
  *immutable inputs* (`01-architecture.md` §5.4) at the storage layer.
- The `ingest.uploads` row carries `immutable_since`, set when validation
  completes; UPDATE on the row's path or bytes is forbidden by grant
  (`06-database-strategy.md` §4).
- Upload deletion is performed only by the `retention` role, in batches, and
  is preceded by an `upload.reclaimed` audit event that includes the
  content_hash so the audit trail still verifies the file's earlier existence.

---

## 6. Audit logs and tamper-evidence

- The audit log is INSERT-only at the DB grant level
  (`04-graph-and-events.md` §12, `06-database-strategy.md` §12).
- The hash chain is verified nightly and on-demand; mismatch raises
  `audit.chain_broken`, blocks releases, and pages the on-call.
- Audit reads are restricted to `auditor` and `tenant_admin` roles,
  workspace-scoped by default; cross-workspace audit reads require the tenant
  auditor role and are explicitly recorded as a `audit.read` event themselves.
- Audit retention ≥ 7 years by default; retention deletes are first-class audit
  events signed by a separate retention key.

---

## 7. Secure file validation

Uploads are untrusted input. The validation layer applies, in order:

1. **Size guard** — abort above per-tenant configured max; never read the whole
   file into memory at once.
2. **Content sniffing** — re-derive MIME from leading bytes; reject mismatches
   between declared and sniffed MIME.
3. **Allowlisted content types** — closed allowlist (csv, tsv, xlsx with no
   macros, json, parquet, xml). Macros-enabled workbooks are rejected.
4. **Magic-byte checks** — zip-based formats (xlsx, parquet, compressed xml)
   are checked for the correct magic bytes; polyglots are rejected.
5. **Schema conformance** — structural validation against the declared schema;
   structural failure ⇒ `upload.rejected`. Per-row errors become claims with
   `validation_issue` records.
6. **Path sanitation** — the only stored path is the server-generated object
   key; client-supplied filenames are stored separately as metadata only, with
   control characters stripped and length capped.
7. **Decompression bomb guard** — bounded expansion ratio and total size
   for any compressed input.
8. **Quarantine** — failed-validation uploads are moved to a quarantine prefix
   to which the backend has read-only access for forensics, never used as a
   source for canonicalization.

---

## 8. Path traversal and path validation

- All object keys are constructed server-side by joining canonical,
- allowlisted components (`tenants/{tenant_id}/workspaces/{workspace_id}/...`).
- Client-supplied paths are rejected; only server-generated keys are stored.
- File-extraction libraries are configured to refuse absolute paths, parent
  traversal (`..`), and symlinks inside archives; extracted files are written
  into a per-job scratch directory with no execution rights.

---

## 9. Background job safety

- Worker credentials are minimally scoped per job kind; for example, an
  extraction job has INSERT-only on `ingest.*` and `claims.claims`, and no
  grant to `canonical`/`graph`/`audit`.
- Workers carry a per-job `correlation_id` and an idempotency key; duplicate
  dispatch cannot create duplicate canonical records.
- Workers fail closed: an unhandled exception leaves no partial canonical
  state; the affected claims remain `pending_review` with a `worker_failed`
  validation issue, and an `audit_job.failed` event is emitted.
- Resource guards (CPU, memory, wall time) cap every job. Exhaustion stops the
  job cleanly and emits a job event; no OOM-driven corruption.

---

## 10. Environment separation

- Distinct secrets, networks, and KMS keys per environment (dev, staging,
  pilot, prod). No shared credentials; no copy-from-prod to non-prod without
  an explicit anonymization step.
- Dev and staging use synthetic data by default. Copying production data to
  staging requires tenant approval, an audit record, time-boxed access, and
  automatic purging after the configured window.

---

## 11. Sandbox isolation for untrusted compute

- ML training and any data-shape extraction logic that runs untrusted file
  parsers (xlsx, xml, custom) executes inside a **sandbox**:
  - separate process/container with no DB driver beyond a read-only snapshot
    interface and write-only `ml_*` / extraction interfaces,
  - restrictive seccomp/AppArmor profile, no network egress, read-only
    filesystem except for a per-job scratch,
  - per-job CPU/memory/timeout limits.

This matches the "bounded ML only" and "immutable inputs" principles and
prevents a malicious upload from reaching the canonical store.

---

## 12. Threat model (high level)

Phase 1 freezes a high-level threat model. Each row names the threat, the
control(s) that mitigate it, and the residual owner (who monitors it).

### 12.1 Unsafe file uploads
- **Threat**: a malicious or malformed file exploits a parser to execute code,
  exhaust resources, or smuggle invalid canonical records.
- **Controls**: §7 validation pipeline, §11 sandbox for parsers, content-type
  allowlist, decompression bomb guard, object quarantine, immutable upload
  retention locked.
- **Owner**: ingestion module owner + security on-call.

### 12.2 Path traversal
- **Threat**: a crafted filename or zip entry escapes its target directory.
- **Controls**: §8 server-only path construction, archive traversal refusal,
  parent-traversal refusal, scratch dir with no exec, sealed runtime image.
- **Owner**: ingestion module owner.

### 12.3 Unauthorized access (API)
- **Threat**: an authenticated user accesses resources outside their role or
  workspace.
- **Controls**: §2 authn/z, §3 workspace/tenant isolation, RLS at the data
  layer, deny-by-default permission matrix, defense in depth across three
  layers, cross-tenant regression tests.
- **Owner**: auth module owner + security on-call.

### 12.4 Evidence tampering
- **Threat**: an actor (internal or external) edits evidence or claims to skew
  decisions.
- **Controls**: immutable uploads (§5), `INSERT`-only grants on evidence,
  per-evidence `content_hash` recomputed on read for tamper detection, audit
  chain hashing every mutation.
- **Owner**: audit module owner.

### 12.5 Audit tampering
- **Threat**: an actor edits or deletes audit events to hide actions.
- **Controls**: INSERT-only grants on `audit.audit_events`, hash chain +
  nightly verification, separate retention role for deletion only, separate
  retention signing key.
- **Owner**: audit/security on-call.

### 12.6 Model misuse
- **Threat**: an ML model is promoted without review, or its output is allowed
  to write facts/decisions, or model artifacts are tampered.
- **Controls**: signed model artifacts, replay-evidence-gated promotion,
  `ml_*` write restrictions only, `confidence ≤ 0.5` enforced on every
  candidate write, shadow lane isolation, admin-only promotion.
- **Owner**: ML module owner.

### 12.7 Workspace data leakage
- **Threat**: cached or in-flight data leaks between workspaces within a
  tenant.
- **Controls**: workspace-scoped query keys, invalidation on switch, RLS
  enforced workspace filter, signed URLs scoped to workspace, telemetry without
  row contents.
- **Owner**: frontend + auth module owners.
- **Notable**: a single bad query at the data layer can produce cross-workspace
  exposure if RLS is misconfigured; the RLS regression suite is therefore a
  release-blocking gate.

### 12.8 Cross-tenant data leakage
- **Threat**: a tenant can see another tenant's rows, object keys, or audit
  events.
- **Controls**: per-tenant schema partitioning, RLS on tenant id, separate
  object-storage prefix roots with separate per-tenant KMS DEKs, separate
  audit chains per (tenant, workspace), no cross-tenant admin APIs without
  platform-admin role (a deployment-platform role, not a tenant role).
- **Owner**: tenant/tenant_admin module owners + security on-call.

### 12.9 Credential and token theft
- **Threat**: refresh tokens, API keys, or workload identities are stolen.
- **Controls**: rotating refresh tokens with reuse detection, short-lived
  workload identities, Argon2id-hashed API keys, immediate revocation, mTLS
  bootstrap, no long-lived service secrets, step-up auth for sensitive actions.
- **Owner**: auth module owner.

### 12.10 Supply-chain dependency compromise
- **Threat**: a third-party dependency introduces a vulnerability or backdoor.
- **Controls**: dependency pinning, SBOM generation per release, daily CVE
  scanning, reproducible builds, image signature verification at deploy time.
- **Owner**: platform/release on-call.

---

## 13. Operational security practices (frozen)

- All admin actions require step-up and emit `audit.*` events.
- All sessions are time-boxed; idle session timeout 30 min; absolute 12h.
- Login attempts are rate-limited per IP and per account; exceeds ⇒
  exponential backoff and alert on N failures in M seconds.
- Cryptography: SHA-256 for hashes and checksums; Argon2id for password/api
  key hashing; AES-256-GCM for column encryption; RS256 for JWTs; P-256 for
  workload-identity signatures. Algorithms are pinned; upgrades via ACR.
- All container images are built from distroless/minimal bases and scanned on
  each build; running-as-root is forbidden.
- Dependency on a single CDN/provider is avoided for portable topologies
  (`11-deployment.md`).

---

## 14. Incident handling stub (Phase 1)

Phase 1 does not produce an exhaustive IR plan. It freezes:
- Detection: audit chain verification job, login anomaly, model signature
  failure, retention/quota violation, RLS regression failure all generate
  alerts routed to security on-call.
- Containment: revocation of refresh tokens, model version revoke,
  workspace suspension (admin-only), upload quarantine.
- Preserve: chain snap and full audit read to a sealed retention object
  for every incident; contact log retention ≥1 year post-incident.
- Recovery: snapshot-rollback to a prior sealed canonical snapshot is possible
  via the `decisions.reverted` workflow; new uploads re-establish evidence.

---

## 15. Compliance posture (Phase 1)

Compliance is application baseline, not a specific certification target:
- Detailed audit trails and immutable inputs support SOC 2 / ISO 27001 control
  patterns but are not Phase 1's content scope.
- Data residency is tenant-configurable at the prefix level; the audit record
  stores the data residency region; cross-region replication is off by default.

---

## 16. Frozen decisions summary

- OIDC authn, RBAC + RLS authorization, three-layer enforcement, deny-by-default.
- Tenant isolation physical (partitions + RLS) and workspace isolation logical.
- Audit INSERT-only with hash chain; uploads object-locked and immutable.
- Upload validation is an 8-step pipeline; parser workloads are sandboxed.
- Path traversal and decompression bombs blocked by construction.
- ML artifacts signed, shadow-isolated, candidate-confidence capped at 0.5.
- Threat model enumerates 10 threats with controls and named owners.
- Cryptography is pinned; admin and sensitive actions require step-up MFA.

Phase 1 proceeds to `10-testing-and-ci-cd.md` on this basis.
