"""Ingestion module — audit.ingestion_log + CSV ingest orchestration.

This is the MVP-side audit log for CSV uploads; it does NOT touch the
existing `app.modules.audit.AuditEvent` (public.audit_events, String(36)
PK). The new table MVP wedge ships under `audit.ingestion_log` per ADR-0006.
"""
