# System boundaries

Status: frozen for the v0.1 sprint. A change here is proposed to the lead,
written into this file, and only then implemented.

Cortex Nexus v0.1 is the data foundation for critical-equipment procurement
intelligence. It takes procurement records in, checks them, keeps them with
their history and their source, and reads them back as one projection, the
World State. It does not judge the data: no risk score, no forecast, no
recommendation exists in this release.

## The flow

```text
 CSV / XLSX file
       |
       v
 INGESTION BOUNDARY        app/ingestion (pure: no database, no HTTP)
   readers -> column mapping -> normalization -> row validation
       |
       v
 INGESTION LEDGER          ingestion_batches, ingestion_rows
   every source row is kept, valid or not
       |
       |  explicit commit request
       v
 DOMAIN SERVICES           app/services
   rules, references, update policy, one transaction per operation
       |
       v
 REPOSITORIES              app/repositories (workspace-scoped queries)
       |
       v
 POSTGRESQL                canonical records + append-only version history
       |
       v
 WORLD STATE SERVICE       read-only projection, assembled on every read
       |
       v
 HTTP API                  app/api (Pydantic schemas in, Pydantic schemas out)
```

## Who owns what

| Layer | Owns | Never does |
|---|---|---|
| PostgreSQL | The canonical facts. Everything else is a view of them. | — |
| HTTP endpoints | Request parsing, workspace context, status code, response schema | Run SQL, apply a business rule that spans records |
| Pydantic schemas | The external contract of requests and responses | Know about tables or transactions |
| Domain services | Invariants, references, the field update policy, the transaction boundary | Parse files, know about HTTP |
| Repositories | Queries, always scoped to a workspace | Commit, decide policy, build responses |
| ORM models | Tables, keys, unique / check / foreign-key constraints | Call anything |
| Readers | Turn bounded CSV/XLSX bytes into rows; never execute cell content; weigh the XML of a workbook before opening it, and refuse one that declares entities or misnumbers its rows | Write to the database; believe the range a worksheet claims |
| Column mapping | Map a source header to a canonical field through a fixed table | Guess; use a language model |
| Normalization | Parse dates, decimals, enums and text strictly | Default an unknown value |
| Row validation | Field, uniqueness, reference and consistency checks against a snapshot it is given | Read or write the database itself |
| Ingestion service | Batch lifecycle: preview, commit, provenance | Let preview change canonical records |
| Data-quality service | Count and name what is missing or invalid | Compress it into one score |
| World State service | Assemble persisted facts into a bounded, deterministic projection | Store a second copy; infer anything |

## Rules that hold across layers

1. **PostgreSQL owns canonical facts.** The API response, the World State and
   any future agent context are projections of persisted rows. Nothing is
   served from a fixture, a cache or a constant.
2. **Ingestion parses and stages.** Reading a file and previewing it writes
   only the ingestion ledger. It cannot create or change a project, supplier,
   equipment record, purchase order, line item, milestone or commitment.
3. **Domain services validate and commit.** Commit is the only path from the
   ledger to canonical records, and it re-checks every reference at that
   moment, inside one transaction.
4. **World State assembles persisted facts.** It is generated on read. There
   is no graph database, no projection table and no cache that could drift.
5. **Facts and inference stay apart.** A supplier's commitment date is a
   fact. "Late", "at risk" and "recommended" are inferences. Inferences get no
   column in a canonical table and no field in the World State.
6. **Every record belongs to one workspace.** A workspace is a data boundary,
   enforced in every query and, where practical, by composite foreign keys.
7. **History is appended, never rewritten.** A changed planned date or
   commitment date is a new version row. No procurement fact is deleted.

## Outside this release

Sequenced for later, on top of this foundation, and deliberately absent now:

- **Deterministic intelligence**: a separate service that reads the World
  State and produces evidence-backed findings (overdue delivery, missing
  acknowledgement, slippage, procurement gap). It never becomes a second
  source of truth.
- **Agents**: none exist. When they do, they interpret evidence and propose;
  they do not change canonical records in this or the next phase.
- **External execution** (supplier emails, purchase-order changes): requires
  a policy check and human approval layer that does not exist yet.
- Authentication, membership and roles; any deployment beyond a developer
  machine; ERP, email, portal or document integrations; a frontend.

## Workspace context in this release

There is no authentication. The process serves exactly one workspace, named
by `NEXUS_DEV_WORKSPACE_ID`, and binds to loopback. A request for any other
workspace id is answered `404 WORKSPACE_NOT_AVAILABLE`, whether or not that
workspace exists. The application refuses to start with this bypass
configured when `APP_ENV` is not `development` or `test`. A workspace id in a
URL is a name, not a credential; before the API is reachable from anywhere
else, this mechanism is replaced by an authenticated principal with verified
membership.
