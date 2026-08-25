# Pilot Shortlist

**Gate**: At least one prospect with all four qualifications ✅ by W2D5.

| # | Prospect | Problem Match (Tier-1 disruption $100K+) | Data Export Path | Decision-Maker Willing | Pilot Window (30d in 60d) | Status |
|---|----------|------------------------------------------|------------------|------------------------|---------------------------|--------|
| 1 | | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| 2 | | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| 3 | | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |

**Shortlist decision** (W2D5):

| Prospect | Chosen? | Reason |
|----------|---------|--------|
| | | |

---

## Synthetic Backtest Fallback

If no real-data partner commits by W2D5:

- **Scenario**: `supplier_delay` (Acme Electronics, 5-day delay)
- **Dataset**: Seeded synthetic company (2 suppliers, 4 components, 2 products, 1 warehouse, 5 orders)
- **Backtest tolerance**: 0.8 (frozen in `BACKTEST_PROTOCOL.md`)
- **Artifact**: `design_partner/BACKTEST_RESULT.md` generated from canonical scenario
- **Label**: "Clearly labeled credible synthetic — not customer data"

This fallback satisfies the pilot acceptance criteria for "one historical disruption backtested" without real customer data.