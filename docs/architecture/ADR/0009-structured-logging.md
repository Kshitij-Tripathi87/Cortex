# ADR-009: Structured Logging

**Status**: Accepted
**Date**: 2026-08-01
**Deciders**: Engineering

## Context

The MVP wedge handles real customer supply-chain data. Plain-text logs are
unsafe (they risk leaking customer names, order values, supplier identities
into third-party log aggregators) and unsearchable (operators cannot query
"show me all requests for workspace X that took > 2 seconds").

## Decision

All log emission uses **structured logging** via `structlog` (already a
project dependency). Every log line carries:

```
request_id     UUID identifying the request
workspace      workspace_id from the authenticated principal
user           user_id from the authenticated principal (nullable for unauthenticated)
scenario       optional: disruption event ID when applicable
duration_ms    request duration in milliseconds (set at completion)
status         HTTP status code (set at completion)
```

Plain-string log messages are forbidden. The pattern is:

```python
log.info(
    "event_name",                  # event key, never a formatted sentence
    key1=value1,
    key2=value2,
)
```

A middleware (`app/infrastructure/logging.py`) binds `request_id`, `workspace`,
and `user` into the context at request entry and emits one summary log line
at request exit.

## Consequences

**Positive**:
- Queryable: operators can filter logs by `workspace`, `status`, `duration`.
- Auditable: `request_id` correlates logs across services.
- Safe by default: no customer/order/pricing data in log messages.

**Negative**:
- Developers must learn the structured pattern. The cost is one-time; the
  benefit is permanent.

## Migration Plan

1. The existing `app/infrastructure/logging.py` already uses `structlog`.
   Extend it with the request-context middleware.
2. Update any existing `log.info("plain string %s", val)` calls to
   structured form. This is an ongoing hygiene task, not a one-shot
   migration; PR review enforces the pattern.
3. Configure any external log shippers (Datadog, CloudWatch) to index on
   the structured fields.

## References

- MVP execution plan Part 10 (security checklist)
