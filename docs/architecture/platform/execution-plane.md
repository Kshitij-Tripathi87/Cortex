# Execution Plane (Draft)

**Status**: Draft
**Scope**: Post-MVP (Phase 6)
**Not active implementation guidance**

---

## 1. Purpose

Turn **approved** decisions into system action. Policy-gated.
Human-supervised. Never autonomous without explicit policy.

---

## 2. Three-Tier Architecture

```
Execution Core
  → Connector Layer
    → Enterprise Systems
```

The Execution Core produces a normalized action envelope. The Connector
Layer translates it to the target system. The Enterprise System
performs it. The core never knows whether the target is SAP or a local
CSV file.

---

## 3. Action Envelope

Every execution request is a typed envelope:

```json
{
  "execution_id": "uuid",
  "decision_id": "uuid",
  "workspace_id": "uuid",
  "action_type": "create_purchase_order",
  "payload": {},

  "policy_gate": {
    "approved_by": "user_uuid",
    "approved_at": "iso-8601",
    "policy_version": "2026.11.1"
  },

  "target": {
    "connector": "sap",
    "system_id": "sap-prod-01"
  },

  "rollback_plan": {
    "compensating_action": "cancel_purchase_order",
    "compensating_payload": {}
  }
}
```

No envelope without `policy_gate` is ever executed.

---

## 4. Connector Layer

| Connector | Direction | Phase |
| --- | --- | --- |
| SAP | writeback | Phase 6 |
| Oracle | writeback | Phase 6 |
| Dynamics 365 | writeback | Phase 6 |
| NetSuite | writeback | Phase 6 |
| CSV | export | Phase 6 |
| Excel | export | Phase 6 |
| REST | generic | Phase 6 |
| Kafka | event stream | Phase 6 |
| MQ | message queue | Phase 6 |

Each connector is a thin adapter that:
1. Validates the envelope against the target system's schema.
2. Translates the envelope to the target's native format.
3. Performs the write.
4. Returns an `Execution Result` to the Memory Plane.

---

## 5. Audit Trail

Every execution records:

- envelope (immutable)
- connector used
- request sent to the system
- response received
- timestamp + operator
- rollback envelope (if applicable)

This trail is append-only and lives in the Memory Plane.

---

## 6. Rollback Safety

Every action must declare a `rollback_plan`. If rollback is not
possible, the action requires a higher policy tier (human-only, no
auto-promotion).

Compensating actions are themselves auditable executions.

---

## 7. MVP Status

The wedge does not execute. It produces a brief; the operator acts in
their own systems. The Execution Plane is a Phase 6 build.
