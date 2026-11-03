# ADR-0016: Object storage for RC1 and production SaaS

- Status: Accepted for RC1 qualification; production provider remains an environment decision
- Date: 2026-11-03
- Decision owners: Cortex engineering

## Context

The current main branch and CI stack reference `minio/minio` images from Docker Hub. Fresh CI runs fail at image pull. MinIO Community Edition's upstream repository now describes source-only distribution and is archived. The remaining `alpine/minio` mirror is useful as a temporary compatibility mirror but its publisher explicitly advises against using its moving `latest-release` tag in production.

Cortex only requires an S3-compatible object API at the application boundary. The backend already accepts endpoint, bucket, region, access key, secret key, and path-style configuration through environment variables.

## Decision

1. Use the official RustFS `1.0.3` container in self-contained development, CI, and staging Compose/Kubernetes manifests for RC1 qualification.
2. Keep the S3 endpoint and SDK boundary unchanged; change only the object-store implementation and credentials/health contract.
3. Keep credentials in environment/secret references. Development defaults are not production credentials.
4. For production multi-tenant SaaS, prefer a managed S3 service with private networking, encryption/KMS, scoped IAM, lifecycle/retention policies, versioning, and tested backup/restore.
5. A single-node RustFS container is not a highly available production storage architecture. Self-managed production RustFS requires a separately designed and qualified multi-node/multi-disk topology, replication, TLS, monitoring, and disaster recovery.

## Compatibility and qualification

- S3 API endpoint: port 9000
- Console: port 9001 (not exposed publicly in production)
- Health endpoint: `GET /health`
- Application uses path-style addressing as currently configured.
- RC1 must verify bucket creation, object put/get/delete, size limits, restart persistence, and backup/restore with the selected provider.

## Consequences

- CI no longer depends on the removed Docker Hub MinIO image.
- The application remains decoupled from the object-store implementation through its S3-compatible client configuration.
- Production rollout is blocked until the managed provider, credentials, encryption, lifecycle, retention, and recovery policy are provisioned and tested.
