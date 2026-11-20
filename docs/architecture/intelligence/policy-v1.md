# Policy v1 and the decision register (task T-A-02)

Status: **PROPOSED. Not signed.** The plan (§21) leaves fifteen decisions to
the lead and says that the implementation must not choose their values
silently. Reconciling the plan with the source (`canonical-input-mapping.md`)
raised thirteen more. This document states a value for each, with the reason,
so that the lead can approve them, change them or leave them open. Until the
sign-off block at the end is filled in, no value below may be written into
code.

## 1. The policy document

One policy exists in v0.2. It is a version-controlled, typed document that
the engine validates when it loads it; an unknown key, a negative number of
days, an unknown status or a time zone that cannot be resolved makes run
creation fail closed. A version is never edited: a changed value is version
2.

| Field | Value proposed for v1 | Decision |
|---|---|---|
| `policy_id` | `procurement-default` | D-09 |
| `policy_version` | `1` | D-09 |
| `effective_from` | `2026-11-19` (the reference date of the demo dataset; no evaluation date before it is accepted under this policy) | D-09 |
| `timezone` | `Asia/Kolkata` | D-03 |
| `enabled_rules` | all five | D-01 |
| `overdue_grace_days` | `0` | D-04 |
| `acknowledgement_due_days_after_issue` | `5` calendar days | D-01, D-03 |
| `acknowledgement_required_statuses` | `ISSUED` | D-02 |
| `critical_equipment_criticality` | `CRITICAL` | plan §4.3 |
| `po_statuses_that_count_as_procured` | `ISSUED`, `ACKNOWLEDGED`, `IN_PRODUCTION`, `PARTIALLY_DELIVERED`, `DELIVERED` | plan §4.3 |
| `po_statuses_that_count_as_open_delivery` | `ISSUED`, `ACKNOWLEDGED`, `IN_PRODUCTION`, `PARTIALLY_DELIVERED` | D-07, D-08 |
| `milestone_overdue_grace_days` | `0` | D-05 |
| `excluded_project_statuses` | `CANCELLED` | D-18 |
| `delivery_risk_severity_policy` | every finding code → `UNCLASSIFIED` | D-06, D-15 |
| `finding_severity_policy_version` | `1` | D-06 |

`enabled_rules` and `excluded_project_statuses` are not in the plan's list of
policy fields (§4.3). They are added so that two decisions are values of the
policy and not constants in code.

A rule that is not in `enabled_rules` is not evaluated, and a run leaves its
findings untouched (`finding-contract.md` §8). The "shadow mode" the plan
allows for the acknowledgement rule is not built in v0.2: if D-01 is not
approved, version 1 is issued without that rule and a later version adds it.

## 2. Decisions the plan left open (§21)

| ID | Decision | Proposed | Reason | Approver | Status |
|---|---|---|---|---|---|
| D-01 | Acknowledgement due days after issue | **5 calendar days** | The plan's recommendation. Not derived from the data | Product lead | PROPOSED |
| D-02 | What proves acknowledgement | A `PO_ACKNOWLEDGEMENT` milestone with status `COMPLETED`, or a purchase-order status other than `ISSUED`. The rule looks only at orders whose status is `ISSUED` | The plan's recommendation, made exact: an order that has moved past `ISSUED` is no longer asked for an acknowledgement | Product lead | PROPOSED |
| D-03 | Weekends and holidays | Calendar days. No working-day or holiday calendar. The evaluation date is the date in `Asia/Kolkata` | Plan §4.4 | Product lead | PROPOSED |
| D-04 | Grace for an overdue delivery | 0 days, a policy value | Plan | Product lead | PROPOSED |
| D-05 | Grace for milestone slippage | 0 days, a policy value | Plan | Product lead | PROPOSED |
| D-06 | Severity thresholds | None. Every finding is `UNCLASSIFIED` | The plan forbids inventing thresholds; the candidates in §6.1 (1–7 days medium, 8–21 high, more critical) are not approved | Product lead | PROPOSED |
| D-07 | What establishes "delivery completed" | Either of two facts, both explicit in the policy: the order's status is outside the open-delivery set (so `DELIVERED` and `CANCELLED` orders are never reported), **or** its `DELIVERY` milestones are completed (D-16, D-17). No delivery date is ever taken from a status | The plan says both: §6.1 excludes delivered orders by status and suppresses on a completed milestone | Product lead | PROPOSED |
| D-08 | Is `PARTIALLY_DELIVERED` an open delivery | Yes | Plan. The schema has no residual quantity, so the whole order stays open until its delivery is recorded complete | Product lead | PROPOSED |
| D-09 | Where the policy is kept | A typed document in the repository, validated on load, with its SHA-256 stored on every run. No policy table in v0.2 | Plan | Lead engineer | PROPOSED |
| D-10 | Run synchronous or durable asynchronous | Synchronous, **subject to task T-F-04**: if the benchmark does not fit the budget agreed after measurement, the phase stops and a worker is proposed separately. No in-process background task | Plan §10.4 | Lead engineer | PROPOSED |
| D-11 | Subject of a commitment threat | The equipment. The purchase order is in the finding key, in a context column and in the evidence | Plan | Lead engineer | PROPOSED |
| D-12 | A resolved finding that reappears | The same finding becomes `ACTIVE` again; `first_detected_at` is kept, `resolved_at` cleared, a new occurrence appended | Plan | Product lead | PROPOSED |
| D-13 | Two runs over the same snapshot | An `Idempotency-Key` is required. The same key returns the same run. Another key creates another run, also over identical data | Plan | Lead engineer | PROPOSED |
| D-14 | How much version history an occurrence keeps | The current version and up to 50 before it, oldest first; when there are more, the newest 50 and a marker with the total. 50 is the bound the World State already uses for history | Plan, made exact | Lead engineer | PROPOSED |
| D-15 | `UNCLASSIFIED` in the severity enumeration | Yes | Plan | Product lead | PROPOSED |

## 3. Decisions raised by reconciling the plan with the source

Each refers to a row of `canonical-input-mapping.md` §4.

| ID | Decision | Proposed | Reason | Approver | Status |
|---|---|---|---|---|---|
| D-16 | A `DELIVERY` or `PO_ACKNOWLEDGEMENT` milestone that is `COMPLETED` without an actual date (X-02) | It counts as completed. The missing date is shown as missing in the evidence | The status is a recorded fact. Requiring the date would report a delivered order as overdue because of a gap in the data, which v0.1 already reports as `MILESTONE_COMPLETED_WITHOUT_ACTUAL_DATE`. The plan's text (§6.1) reads the other way, so this needs an explicit yes | Product lead | PROPOSED |
| D-17 | Several `DELIVERY` milestones on one order (X-01) | Delivery is recorded complete when at least one `DELIVERY` milestone is not `CANCELLED` and every such milestone is `COMPLETED` | A part delivery leaves the order open, as D-08 does for the status | Product lead | PROPOSED |
| D-18 | Cancelled and draft parents (X-04, X-05) | (a) No rule evaluates records of a project whose status is in `excluded_project_statuses`. (b) R3 evaluates milestones only of orders in `po_statuses_that_count_as_procured`. (c) R4 skips equipment whose procurement status is `CANCELLED`, as R5 does by the plan | v0.1 leaves cancelled records out of its data-quality warnings for the same reason: nothing more is expected of them | Product lead | PROPOSED |
| D-19 | Status set of R4 (X-03) | The open-delivery set. An order with status `DELIVERED` is not reported as a threat | Consistent with R1 and D-07 | Product lead | PROPOSED |
| D-20 | Outcomes that cannot be evaluated (X-06) | Stored per run in a table of their own, counted on the run, readable through one route. They are never findings | The plan requires them to be shown and names no place for them | Lead engineer | PROPOSED |
| D-21 | Source of a value of a mutable record (X-07) | Evidence cites the row that created the record and the row that last changed it, and says for each whether it states the value used. Where no row does: `SOURCE_NOT_RECORDED`. Versions keep their exact source row. The missing field-level history is recorded as a limitation of v0.2 | v0.1 has no change log of canonical writes, and adding one changes the canonical model | Lead engineer | PROPOSED |
| D-22 | Metrics (X-10) | One structured log event per run with the durations of the three stages, the counts by entity family and by finding code, and the outcome; the durations are also stored on the run. No metrics endpoint and no new dependency in v0.2 | The stack has no exporter. The names of plan §13.2 are kept for the day one is chosen | Lead engineer | PROPOSED |
| D-23 | Error code of a missing run or finding (X-09) | `404 NOT_FOUND`, as every v0.1 route answers. `INTELLIGENCE_RUN_NOT_FOUND` is not added | One answer for "does not exist" and "is not yours" is a rule of the v0.1 contract | Lead engineer | PROPOSED |
| D-24 | Bounds of a supplied evaluation date (X-12) | Not later than today in the policy time zone; not earlier than `effective_from`; not earlier than the evaluation date of the workspace's latest completed run | Current findings must not move backwards, and a date in the future must not block every later run. Historical re-evaluation is not in v0.2 | Lead engineer | PROPOSED |
| D-25 | Runs at the same time (X-13) | At most one run of a workspace is in progress, enforced by a partial unique index. A second request is answered `429 INTELLIGENCE_CAPACITY_EXCEEDED`. A run left in progress by a crashed process is failed as `ABANDONED` after a fixed time | With one run at a time, the order of snapshots is the order of results | Lead engineer | PROPOSED |
| D-26 | An overdue order and its own late `DELIVERY` milestone (X-17) | Both are reported | They compare different dates: the supplier's commitment and the plan. Merging them would be a judgement the plan does not make | Product lead | PROPOSED |
| D-27 | A milestone completed late (X-18) | Reported as the plan says, and it stays `ACTIVE` for as long as the milestone is eligible: until it is re-planned, cancelled, or its order leaves the eligible statuses | Faithful to the plan. The list of active findings will therefore keep past lateness; to be looked at again once the list is in use | Product lead | PROPOSED |
| D-28 | Time-zone data (X-11) | Add the `tzdata` package to the locked dependencies when the policy loader is built (task T-B-04) | `Asia/Kolkata` must resolve on every machine the suite runs on; where it cannot, the policy is invalid and no run is created | Lead engineer | PROPOSED |

## 4. What stays open after a sign-off

| Item | State |
|---|---|
| Severity thresholds | Not decided (D-06). Every finding is `UNCLASSIFIED` until a later policy version says otherwise |
| Working days and holidays | Not in v0.2 (D-03) |
| Run budget and supported workspace size | Decided after the first measurements (task T-F-04, plan §16) |
| Field-level history of mutable records | A limitation (D-21) |

## 5. Sign-off

| | |
|---|---|
| Status | **NOT SIGNED** |
| Approver | — |
| Date | — |
| How it was given | — |
| Exceptions | — |

Merging the pull request that carries this document with the status
`NOT SIGNED` approves nothing: the values stay proposals.
