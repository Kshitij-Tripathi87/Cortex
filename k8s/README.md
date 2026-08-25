# Cortex Helm Chart

## Prerequisites

- Kubernetes 1.25+
- Helm 3.10+
- cert-manager (for TLS)
- nginx-ingress (or compatible ingress controller)
- Prometheus (optional, for metrics)
- Grafana (optional, for dashboards)

## Installation

### 1. Create namespace and secrets

```bash
kubectl create namespace cortex

# Create secrets (replace with your secret management solution)
kubectl create secret generic cortex-secrets \
  --from-literal=DB_USER=cortex \
  --from-literal=DB_PASSWORD=$(openssl rand -base64 32) \
  --from-literal=S3_ACCESS_KEY=$(openssl rand -hex 10) \
  --from-literal=S3_SECRET_KEY=$(openssl rand -base64 32) \
  -n cortex
```

### 2. Apply infrastructure

```bash
kubectl apply -f k8s/infrastructure.yaml
```

Wait for infrastructure to be ready:

```bash
kubectl wait --for=condition=available deployment/cortex-postgres -n cortex --timeout=120s
kubectl wait --for=condition=available deployment/cortex-redis -n cortex --timeout=60s
kubectl wait --for=condition=available deployment/cortex-minio -n cortex --timeout=120s
```

### 3. Run migrations

```bash
kubectl run cortex-migrate \
  --image=cortex-backend:0.3.0 \
  -n cortex \
  --rm -it \
  --env-from=configmap/cortex-config \
  --env-from=secret/cortex-secrets \
  -- alembic upgrade head
```

### 4. Apply base deployment

```bash
kubectl apply -f k8s/base.yaml
```

### 5. Verify deployment

```bash
# Check pods are running
kubectl get pods -n cortex

# Check services
kubectl get svc -n cortex

# Check backend health
kubectl port-forward svc/cortex-backend 8000:8000 -n cortex &
curl http://localhost:8000/healthz

# Check frontend
kubectl port-forward svc/cortex-frontend 3000:3000 -n cortex &
curl http://localhost:3000
```

### 6. Configure ingress (optional)

Update `k8s/base.yaml` with your domain:

```yaml
spec:
  rules:
    - host: cortex.your-domain.com
```

Apply cert-manager issuer if using TLS:

```bash
kubectl apply -f k8s/issuer.yaml
```

## Configuration

### Environment Variables

See `k8s/base.yaml` ConfigMap for all available options.

### Resource Limits

Default resource requests/limits:

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Backend   | 250m        | 1000m     | 512Mi          | 1Gi          |
| Frontend  | 100m        | 500m      | 256Mi          | 512Mi        |
| Postgres  | 250m        | 1000m     | 512Mi          | 2Gi          |
| Redis     | 100m        | 500m      | 128Mi          | 512Mi        |
| MinIO     | 250m        | 1000m     | 512Mi          | 2Gi          |

### Scaling

Backend autoscaling (HPA):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: cortex-backend-hpa
  namespace: cortex
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: cortex-backend
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

## Monitoring

### Metrics Endpoints

- Backend: `/metrics` (Prometheus format)
- Health: `/healthz`
- Readiness: `/readyz`

### Grafana Dashboards

Import dashboard JSON from `k8s/grafana/` after deployment.

## Backup

### Database Backup

```bash
kubectl run postgres-backup \
  --image=postgres:16-alpine \
  -n cortex \
  --rm -it \
  --env PGPASSWORD=$(kubectl get secret cortex-secrets -n cortex -o jsonpath='{.data.DB_PASSWORD}' | base64 -d) \
  -- pg_dump -h cortex-postgres -U cortex cortex > backup.sql
```

### MinIO Backup

Use MinIO's `mc` client:

```bash
mc alias set cortex-minio http://cortex-minio:9000 \
  $(kubectl get secret cortex-secrets -n cortex -o jsonpath='{.data.S3_ACCESS_KEY}' | base64 -d) \
  $(kubectl get secret cortex-secrets -n cortex -o jsonpath='{.data.S3_SECRET_KEY}' | base64 -d)

mc mirror cortex-minio/cortex-uploads ./backup-minio
```

## Upgrade

### 1. Update image tags in k8s/base.yaml

```yaml
spec:
  template:
    spec:
      containers:
        - image: cortex-backend:0.4.0  # Update version
```

### 2. Run migrations

```bash
kubectl run cortex-migrate \
  --image=cortex-backend:0.4.0 \
  -n cortex \
  --rm -it \
  --env-from=configmap/cortex-config \
  --env-from=secret/cortex-secrets \
  -- alembic upgrade head
```

### 3. Rolling update

```bash
kubectl rollout restart deployment/cortex-backend -n cortex
kubectl rollout restart deployment/cortex-frontend -n cortex
kubectl rollout status deployment/cortex-backend -n cortex
kubectl rollout status deployment/cortex-frontend -n cortex
```

## Troubleshooting

### Check pod logs

```bash
kubectl logs -n cortex -l app=cortex-backend -f
kubectl logs -n cortex -l app=cortex-frontend -f
```

### Exec into pod

```bash
kubectl exec -it -n cortex deployment/cortex-backend -- /bin/bash
```

### Database connection issues

```bash
kubectl exec -it -n cortex deployment/cortex-postgres -- psql -U cortex -d cortex
```

### MinIO access

Access MinIO console at: `http://cortex-minio:9001` (port-forward if needed)

## Uninstall

```bash
kubectl delete namespace cortex
```

⚠️ This will delete all data. Backup first!