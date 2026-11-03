# Nexus v0.8.5 Execution Board

## Immediate blockers

### B3/B6 frontend canonical rewire
Status: BLOCKED until the validated implementation artifact is restored to the remote PR branch.

Required proof:
- canonical `/nexus/*` data calls;
- no authenticated `/workspace/*` data calls;
- no demo risk/SKU/session data;
- workspace identity from authenticated context;
- request/trace identifiers surfaced;
- golden-path and role-gating E2E.

### Golden customer path
Blocked until B3/B6 is merged and the full UI path is verified on real persisted data.

## Current green foundation

- B4 durable realtime is merged in `main`.
- v0.8.4 ML registry/inference/provenance is merged.
- B1/B2 onboarding/authentication is merged.
- B3 backend canonical risks/signals/scenarios/evidence/approval APIs are merged.

## Next slices

1. Reconcile and push B3/B6.
2. Merge after CI and E2E validation.
3. Execute B9 deployment and DR.
4. Execute final security/load/chaos validation.
5. Execute B10 billing, entitlements, admin and transactional email.
6. Run fresh-customer rehearsal.
7. Freeze `v0.8.5-rc1`.

## B9 exit criteria

- staging deployment;
- HTTPS/DNS/secrets;
- migration rehearsal;
- backup;
- clean restore;
- World State/decision/evidence verification after restore;
- API/worker/relay/Redis/DB/realtime failure drills;
- rollback rehearsal.

## B10 exit criteria

- subscription state;
- server-side entitlements;
- workspace usage limits;
- minimal admin/support visibility;
- transactional email for reset/onboarding/critical notifications.

## Release definition

Nexus is launch-ready only after the authenticated customer workflow, operational infrastructure, recovery controls, SaaS enforcement and final security/reliability gates are all green.