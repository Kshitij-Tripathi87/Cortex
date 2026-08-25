# Pilot Readiness Checklist

**Must complete before first discovery call (W1D5 gate):**

## Wedge Freeze
- [ ] `v1.0.0-wedge` tagged on `main`
- [ ] ADR-0013 committed (`docs/architecture/ADR/0013-wedge-freeze.md`)
- [ ] Freeze entry appended to `DECISIONS.md`
- [ ] No active PRs modify frozen surfaces (propagation, impact, confidence, recommendations, timeline, brief, supplier_delay scenario, Morning Brief components)

## Demo & Materials
- [ ] `DEMO.md` runs end-to-end on local dev (backend + frontend)
- [ ] `design_partner/ONE_PAGER.md` current
- [ ] `design_partner/TECHNICAL_DEEP_DIVE.md` current
- [ ] `design_partner/ROI_CALCULATOR.md` current
- [ ] `design_partner/INTEGRATION_GUIDE.md` current
- [ ] `design_partner/PILOT_AGREEMENT.md` current
- [ ] `design_partner/NDA_TEMPLATE.md` created (this file's sibling)

## Legal / Data
- [ ] NDA template reviewed by counsel (or acceptable standard MNDA)
- [ ] Data handling addendum: "Customer data never leaves Customer deployment; Cortex runs on Customer infra"
- [ ] Pilot agreement template ready for signature
- [ ] IP clause: Cortex retains IP on math/engine; Customer owns their data and outputs

## Backend Readiness
- [ ] `scripts/run_backtest.py --scenario supplier_delay` passes (≥ 0.8 tolerance)
- [ ] CSV loader (`scripts/load_csv.py`) tested on a non-seeded dataset
- [ ] `POST /api/v1/briefs/supplier-failure` returns full `DecisionBriefResponse` v0.3.0
- [ ] Backend logs show no errors on seeded scenario

## Frontend Readiness
- [ ] `npm run typecheck` passes
- [ ] Morning Brief page loads with seeded UUIDs
- [ ] Role switch (CFO / COO / Logistics / Procurement) reorders sections
- [ ] All 7 components render without console errors
- [ ] Evidence drawer tabs work (components / products / warehouses / orders)

## Outreach Ops
- [ ] `design_partner/PROSPECTS.md` populated with 5–10 names
- [ ] Calendly / scheduling link ready
- [ ] 15-min discovery call script prepared (pain points, current workflow, exports, freshness, timing, willingness)
- [ ] Internal slack channel for pilot coordination: `#cortex-pilot`

---

## W1D5 Sign-off

**Founder/CTO**: ________________________  Date: ___________

All ⬜ items above are ✅ or explicitly deferred with a written reason in `DECISIONS.md`.