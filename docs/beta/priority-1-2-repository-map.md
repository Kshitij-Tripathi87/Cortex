# Priority 1 and 2 repository map — remote baseline audit

**Audit date:** 2026-11-04  
**Repository:** \`Kshitij-Tripathi87/Cortex\`  
**Audited ref:** \`main\` at \`15edf972f131fbf7f85cca66b3371f8421ff367f\`

> Scope note: this is an audit of the GitHub \`main\` snapshot above. The founder separately reported newer local work on 2026-11-03, including a redesigned cockpit and environment setup. That local working tree was not available to this worker. Do not treat this remote branch as a mirror of the local Windows checkout, and do not reset or overwrite local changes when integrating this work.

## Existing modules to reuse

| Concern | Existing remote module | Finding |
|---|---|---|
| CSV ingestion | \`backend/app/modules/ingestion\` | Existing synchronous CSV ingestion and upload/status API. |
| Source artifacts | \`backend/app/modules/sources\` | Content-addressed immutable storage, SHA-256, file profiling and audit events. |
| Dataset validation | \`backend/app/modules/datasets\` | Dataset registry, validation and statistics already exist. |
| Supply-chain entities | \`backend/app/modules/supply_chain\` | Workspace-scoped repositories for suppliers, components, products, warehouses, BOM, inventory and customer orders. |
| Canonical operational state | \`backend/app/modules/world\` | Versioned World State persistence and projection. |
| Graph | \`backend/app/modules/graph\` | Graph compiler, repository, traversal and validation. |
| Disruption impact | \`backend/app/modules/disruption\` | Existing propagation/impact engines and supplier-delay scenario. |
| API wiring | \`backend/app/api/v1/router.py\` | Existing sources, ingestion, graph, world and readiness routers. |
| Schema history | \`backend/alembic/versions\` | Existing migrations through revision 016. |

## Confirmed implementation gaps in the audited remote snapshot

1. \`Inventory\` stores \`quantity\` and \`safety_stock\`, but does not declare whether \`quantity\` is physical on-hand or available-to-use, nor does it separately model reserved and blocked stock.
2. \`BillOfMaterials\` stores a product/component pair and \`quantity_per_unit\`; it does not have explicit revision, facility applicability, or effectivity dates.
3. \`Order\` represents customer demand. A distinct production-order entity and purchase-order-line entity were not present in the audited \`supply_chain.models\` file.
4. \`MvpDatasetType\` covers suppliers, components, warehouses, factories, products, customers, edges, inventory, BOM and customer orders. It does not include purchase-order lines or production orders.
5. \`ingest_csv_streaming\` stages the upload to a temporary file and then materializes the full bytes and parsed row list; it is not end-to-end streaming.
6. The strict ingestion path can return a failed log after earlier rows have been flushed. The API route commits after a normal service return. Without a dataset-level savepoint, earlier accepted rows can be committed despite strict mode reporting failure.
7. Partial ingestion catches row insert exceptions without an explicit per-row savepoint. A database integrity error can leave the SQLAlchemy transaction failed, preventing later rows from being processed reliably.
8. The parser uses \`csv.DictReader\` and whitespace trimming but does not explicitly reject duplicate normalized headers, blank headers, or malformed row widths.
9. The current disruption propagation engine is a dependency-discovery algorithm; it is not a quantity-aware, time-phased material availability calculation.
10. The existing business impact module contains hard-coded fallback prices, margin and penalty percentages. Those are not suitable as authoritative financial outputs for the initial shortage calculation.

## Changes in this implementation branch

- Add a pure deterministic planning core at \`backend/app/modules/supply_chain/planning.py\`.
- Add independent tests at \`backend/tests/test_material_planning.py\`.
- Harden CSV structural parsing and ingestion transaction handling in \`backend/app/modules/ingestion/service.py\`.
- Persist the file SHA-256 digest with the existing ingestion audit record, add a nullable migration, and return it from the existing ingestion API.
- Do not create a second ingestion route, graph service, or World State store.

## Intentionally not claimed as complete by this branch

The planning core is a calculation layer, not yet a database-backed P2 product workflow. Full P1/P2 completion still requires repository-backed schema mapping/staging/claim provenance, batch mapping review and readiness wiring, purchase-order and production-order persistence, BOM revision/effectivity persistence, inventory quantity-basis and reservation persistence, snapshot creation, and API/UI integration. Those tasks require integration against the founder's newer local branch and its actual working tree before final beta release.
