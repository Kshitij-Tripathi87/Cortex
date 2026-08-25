# PILOT_BOARD.md — Week-by-Week Tracker

Owner: Founder / CTO | Status: **⬜ Not started | 🟡 In progress | ✅ Done**

---

## Week 1 — Freeze, Outreach, Readiness

| # | Day | Task (from execution board) | Concrete artifact | Owner | W1-Q1 | W1-Q2 | W1-Q3 | W1-Q4 |
|---|-----|-----------------------------|-------------------|-------|-------|-------|-------|-------|
| W1D1 | Mon | Tag wedge as `v1.0.0-wedge`; freeze schema/API/scoring/brief | `git tag v1.0.0-wedge` + ADR-0013 | Founder/CTO | ⬜ | | | ⬜ |
| W1D2 | Tue | Target list of 5–10 design partners | `design_partner/PROSPECTS.md` | Founder | | ⬜ | | ⬜ |
| W1D3 | Wed | Outreach email template | `design_partner/OUTREACH_EMAIL_TEMPLATE.md` | Founder | | ⬜ | | ⬜ |
| W1D4 | Thu | Pilot readiness checklist | `design_partner/PILOT_READINESS_CHECKLIST.md` | Founder | | ⬜ | | ⬜ |
| W1D5 | Fri | Confirm canonical scope (supplier-delay only); NDA template | `design_partner/NDA_TEMPLATE.md` + `DECISIONS.md` append | Founder | ⬜ | | ⬜ | ⬜ |

**W1 weekly questions (answer all four):**
1. Did we move the wedge forward? ⬜
2. Did we keep the scope narrow? ⬜
3. Did we get closer to a real operator saying "I would use this"? ⬜
4. Did we avoid drifting into platform work? ⬜

---

## Week 2 — Design Partner Discovery and Data Fit

| # | Day | Task | Concrete artifact | Owner | W2-Q1 | W2-Q2 | W2-Q3 | W2-Q4 |
|---|-----|------|-------------------|-------|-------|-------|-------|-------|
| W2D1 | Mon | Discovery call #1–#2; capture per-prospect notes | `design_partner/DISCOVERY_NOTES/{prospect-slug}.md` | Founder + Backend | ⬜ | | | ⬜ |
| W2D2 | Tue | Discovery call #3–#4 | … | Founder + Backend | ⬜ | | | ⬜ |
| W2D3 | Wed | Discovery call #5; data-fit assessment vs canonical schema | `design_partner/DATA_FIT.md` | Founder + Backend | ⬜ | ⬜ | | ⬜ |
| W2D4 | Thu | Confirm single KPI per prospect (rev / margin / stockout / SLA / recovery) | per-prospect note updated | Founder | ⬜ | | | ⬜ |
| W2D5 | Fri | Pilot shortlist (≥1 with problem + data + willingness); synthetic fallback plan | `design_partner/PILOT_SHORTLIST.md` | Founder | ⬜ | ⬜ | ⬜ | ⬜ |

**W2 weekly questions:**
1. Did we move the wedge forward? ⬜
2. Did we keep the scope narrow? ⬜
3. Did we get closer to a real operator saying "I would use this"? ⬜
4. Did we avoid drifting into platform work? ⬜

---

## Week 3 — Pilot Data Mapping and Backtest Setup

| # | Day | Task | Concrete artifact | Owner | W3-Q1 | W3-Q2 | W3-Q3 | W3-Q4 |
|---|-----|------|-------------------|-------|-------|-------|-------|-------|
| W3D1 | Mon | Map partner CSVs → canonical schema (8 files from `INTEGRATION_GUIDE.md`) | `design_partner/pilots/{name}/SCHEMA_MAPPING.md` | Backend | ⬜ | | | ⬜ |
| W3D2 | Tue | Validate required columns + FKs; normalize | `VALIDATION_REPORT.md` + run log | Backend | ⬜ | | | ⬜ |
| W3D3 | Wed | Import pilot dataset; idempotent loader | pilot SQLite snapshot | Backend | ⬜ | | | ⬜ |
| W3D4 | Thu | Generate backward-looking "Supplier X delayed N days" event + Morning Brief JSON | `pilot_scenario.json` + `brief.json` | Backend | ⬜ | | | ⬜ |
| W3D5 | Fri | Freeze backtest tolerance (0.8) + protocol | `BACKTEST_PROTOCOL.md` | QA / CTO | ⬜ | | ⬜ | ⬜ |

**W3 weekly questions:**
1. Did we move the wedge forward? ⬜
2. Did we keep the scope narrow? ⬜
3. Did we get closer to a real operator saying "I would use this"? ⬜
4. Did we avoid drifting into platform work? ⬜

---

## Week 4 — Pilot Review and Backtest

| # | Day | Task | Concrete artifact | Owner | W4-Q1 | W4-Q2 | W4-Q3 | W4-Q4 |
|---|-----|------|-------------------|-------|-------|-------|-------|-------|
| W4D1 | Mon | Run end-to-end backtest | `BACKTEST_RESULT.md` | QA | ⬜ | | ⬜ | ⬜ |
| W4D2 | Tue | Compare predicted vs actual (rev risk, time-to-consequence, recommended action) | append to `BACKTEST_RESULT.md` | QA | ⬜ | | ⬜ | ⬜ |
| W4D3 | Wed | Present Morning Brief to external operator | meeting notes | Founder | ⬜ | | ⬜ | ⬜ |
| W4D4 | Thu | Capture feedback: clear / missing / untrustworthy / would-use | `OPERATOR_FEEDBACK.md` | Founder | ⬜ | | ⬜ | ⬜ |
| W4D5 | Fri | Update `CURRENT_STATUS.md` + `DECISIONS.md`; pick exit path A / B / C | ADR-0014 filled | Founder | ⬜ | ⬜ | ⬜ | ⬜ |

**W4 weekly questions:**
1. Did we move the wedge forward? ⬜
2. Did we keep the scope narrow? ⬜
3. Did we get closer to a real operator saying "I would use this"? ⬜
4. Did we avoid drifting into platform work? ⬜

**W4 exit criteria (ALL MUST BE ✅ for Path A):**
- [ ] Backtest result is documented (≥ 0.8 tolerance).
- [ ] Operator can understand the brief.
- [ ] Operator can point to at least one sub-score they trust.
- [ ] Operator can say what action they would take.

---

## Week 5 — Fix the One Highest-Value Gap (Conditional)

*Only if W4 acceptance fails on one fixable gap.*

| # | Day | Task | Concrete artifact | Owner |
|---|-----|------|-------------------|-------|
| W5D1 | Mon | Isolate the single gap from `OPERATOR_FEEDBACK.md` | `GAP_FIX.md` (gap + fix plan) | Backend or Frontend |
| W5D2–W5D3 | Tue–Wed | Implement targeted fix | code change + test | Backend or Frontend |
| W5D4 | Thu | Re-run backtest or brief for the pilot scenario | updated `BACKTEST_RESULT.md` / `brief.json` | QA |
| W5D5 | Fri | Re-evaluate exit path against ADR-0014 | updated ADR-0014 | Founder |

Allowed fixes: trust explanation clarity, Morning Brief wording, schema mapping robustness, data validation messages, genuine propagation/recommendation bug, missing evidence link.

---

## ADR Index

| ADR | Title | Status |
|-----|-------|--------|
| 0013 | Wedge Freeze for the Pilot Phase | ✅ Accepted |
| 0014 | Pilot Exit Decision (Path A / B / C) | ⬜ Template (fill at W4D5) |

---

## Quick Links

- `design_partner/PROSPECTS.md`
- `design_partner/OUTREACH_EMAIL_TEMPLATE.md`
- `design_partner/PILOT_READINESS_CHECKLIST.md`
- `design_partner/NDA_TEMPLATE.md`
- `design_partner/DISCOVERY_NOTES/` (per-prospect)
- `design_partner/PILOT_SHORTLIST.md`
- `design_partner/DATA_FIT.md`
- `design_partner/pilots/{name}/SCHEMA_MAPPING.md`
- `design_partner/VALIDATION_REPORT.md`
- `design_partner/BACKTEST_PROTOCOL.md`
- `design_partner/BACKTEST_RESULT.md`
- `design_partner/OPERATOR_FEEDBACK.md`
- `design_partner/GAP_FIX.md` (if needed)
- `docs/architecture/ADR/0013-wedge-freeze.md`
- `docs/architecture/ADR/0014-pilot-exit-decision.md`