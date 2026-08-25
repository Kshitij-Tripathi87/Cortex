# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

We take the security of Cortex seriously. If you believe you have found a security vulnerability, please report it to us as described below.

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to **security@cortex.example.com** (replace with actual security contact).

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

After the initial reply to your report, the security team will keep you informed of the progress towards a fix and full announcement, and may ask for additional information or guidance.

## Security Best Practices

### Authentication & Authorization
- All API endpoints require authentication via Bearer tokens
- Row-Level Security (RLS) enforces tenant isolation at the database level
- Role-based access control (RBAC) for administrative operations

### Data Protection
- Content-addressed storage with SHA-256 verification
- Immutable audit logging for all data operations
- Secrets scanner detects AWS/GitHub keys before deployment

### Infrastructure
- Docker containers run as non-root users
- PostgreSQL RLS policies prevent cross-tenant data access
- OpenTelemetry tracing for security audit trails

## Known Limitations

- RLS policies must be carefully reviewed when adding new tables
- Content-addressed storage relies on SHA-256 collision resistance
- Audit logs are append-only; deletion requires administrative access

## Security Audit History

| Date       | Auditor          | Summary                          |
| ---------- | ---------------- | -------------------------------- |
| 2026-07-01 | Internal Team    | RC-1 security gate passed        |