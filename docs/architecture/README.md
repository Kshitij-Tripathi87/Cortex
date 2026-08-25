# Cortex Architecture Documentation

Cortex distinguishes **active** architecture (governing current
engineering) from **platform** architecture (the long-term North Star).

## Layout

```
docs/architecture/
├── README.md             ← you are here
├── ADR/                  ← accepted architectural decisions
├── active/               ← current engineering source of truth
│   └── wedge-architecture-v1.md
├── platform/             ← future platform (draft, not active)
│   ├── cortex-platform-v2.md   ← master North Star
│   ├── world-model.md
│   ├── multi-agent-runtime.md
│   ├── intelligence-plane.md
│   ├── decision-memory.md
│   └── execution-plane.md
└── roadmap/              ← phase-by-phase migration
    ├── phase-2.md
    ├── phase-3.md
    ├── phase-4.md
    └── long-term-vision.md
```

## Reading order

1. **Engineers** — read `active/` only. That is the contract.
2. **Strategists** — read `platform/cortex-platform-v2.md` first, then
   its sub-documents.
3. **Planners** — read `roadmap/` to understand when platform
   components graduate from draft to active.

## Governance

- `active/` is the **only** folder that governs current PRs.
- `platform/` and `roadmap/` are drafts. They do not justify work.
- A platform component becomes active only via a new ADR.

## Conflict Resolution

If `platform/` and `active/` disagree, `active/` wins. Escalation is
via a new ADR, not a silent edit.
