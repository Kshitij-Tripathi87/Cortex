# Cortex — Integration Guide

For: Integration Engineer, ERP Administrator.
Read time: ~8 minutes.

## What you are doing

You are loading your supply-chain data into Cortex so it can compute
decision briefs. The MVP connector is CSV. There are eight files.

## The eight files

### 1. `suppliers.csv`

```csv
id,name,country,tier,lead_time_days
11111111-1111-1111-1111-111111111111,Acme Electronics,US,1,21
```

- `id` — UUID, primary key.
- `name` — display name.
- `country` — ISO-3166 alpha-2.
- `tier` — `1`, `2`, or `3` (1 = direct, strategic).
- `lead_time_days` — typical replenishment in days.

### 2. `components.csv`

```csv
id,sku,name,unit_cost_usd
22222222-2222-2222-2222-222222222222,RES-0805-10K,10kΩ resistor,0.02
```

### 3. `products.csv`

```csv
id,sku,name
33333333-3333-3333-3333-333333333333,CTRL-A1,Controller A1
```

### 4. `boms.csv`

```csv
product_id,component_id,qty_per_unit
33333333-3333-3333-3333-333333333333,22222222-2222-2222-2222-222222222222,4
```

- One row per `(product, component)` pair.
- `qty_per_unit` is a positive integer.

### 5. `warehouses.csv`

```csv
id,name
44444444-4444-4444-4444-444444444444,Plano TX DC
```

### 6. `inventory.csv`

```csv
warehouse_id,component_id,quantity,safety_stock,daily_usage
44444444-4444-4444-4444-444444444444,22222222-2222-2222-2222-222222222222,1000,200,80
```

- `safety_stock` is the floor below which you reorder.
- `daily_usage` is the average burn rate.

### 7. `orders.csv`

```csv
id,customer_id,product_id,quantity,due_date,status
55555555-5555-5555-5555-555555555555,66666666-6666-6666-6666-666666666666,33333333-3333-3333-3333-333333333333,50,2026-09-01,open
```

- `status` is one of `open`, `partial`, `shipped`, `cancelled`.
- `due_date` is ISO-8601 date.

### 8. `supplier_components.csv`

```csv
supplier_id,component_id
11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222
```

- The many-to-many between suppliers and components.

## How to load

```bash
cd backend
python scripts/load_csv.py \
  --workspace 55555555-5555-5555-5555-555555555555 \
  --data-dir /path/to/your/csvs/
```

The loader is idempotent. Re-uploading the same file is a no-op.

## How to verify

```bash
curl -X POST http://localhost:8000/api/v1/briefs/supplier-failure \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "55555555-5555-5555-5555-555555555555",
    "supplier_id": "11111111-1111-1111-1111-111111111111",
    "severity": "critical"
  }'
```

A successful response is a `DecisionBrief` with `contract_version: "0.3.0"`.

## Common errors

| Error | Cause | Fix |
| --- | --- | --- |
| `MissingEntity` | A UUID in `boms.csv` is not in `components.csv` | Re-export with all rows |
| `DuplicateKey` | Two rows with the same primary key | Dedupe before upload |
| `InvalidStatus` | `orders.csv` has a status not in the enum | Use the four valid values |
| `NoGraph` | Loader could not build the graph | Check for orphan IDs |

## What comes after the pilot

- Direct ERP connectors (SAP, Oracle, NetSuite) on the roadmap.
- A streaming mode for high-velocity inventories.
- Webhook callbacks when the brief crosses a severity threshold.

None of these are required for the pilot.
