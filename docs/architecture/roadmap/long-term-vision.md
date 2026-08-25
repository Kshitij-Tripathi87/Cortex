# Long-Term Vision (Draft)

**Status**: Draft
**Scope**: 12–36 months
**Not active implementation guidance**

---

## Phases at a Glance

| Phase | Plane | Status | Year |
| --- | --- | --- | --- |
| 0 | Freeze | ✅ Done | 2026 |
| 1 | Operational | ✅ Done | 2026 |
| 2 | Pilot Hardening | 🟡 Active | 2026 |
| 3 | Memory | ⬜ Future | 2026–2027 |
| 4 | Intelligence | ⬜ Future | 2027 |
| 5 | Multi-Agent Runtime | ⬜ Future | 2027 |
| 6 | Execution Plane | ⬜ Future | 2027–2028 |

---

## The Long-Term Shape

Cortex graduates from a deterministic brief into a layered decision
system:

- **Operational** tells the user what is happening and what to do.
- **Memory** stores what happened and what was chosen.
- **Intelligence** learns from history.
- **Multi-Agent Runtime** coordinates specialized work.
- **Execution Plane** performs approved actions under policy.

---

## Capability Domains Active by End of Vision

| Capability | Operational | Memory | Intelligence | Runtime | Execution |
| --- | :-: | :-: | :-: | :-: | :-: |
| Evidence | ✅ | ⬜ | ⬜ | ⬜ | — |
| Graph | ✅ | ⬜ | ⬜ | ⬜ | — |
| Decision | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Simulation | ✅ | ⬜ | ⬜ | ⬜ | — |
| Memory | — | ⬜ | ⬜ | ⬜ | — |
| Execution | — | ⬜ | ⬜ | ⬜ | ⬜ |
| Learning | — | ⬜ | ⬜ | ⬜ | — |

✅ = shipped, ⬜ = future, — = N/A.

---

## What the Vision Does Not Include

- A generic AI copilot.
- A plugin marketplace.
- Edge / offline deployment.
- SSO/billing/admin infrastructure (until pilot revenue justifies).
- A Kubernetes-native multi-service scale-out (until load justifies).

---

## How the Vision Stays Honest

Every phase has acceptance criteria grounded in:
- an offline benchmark,
- a held-out replay set,
- an operator review.

No phase graduates on ambition alone.
