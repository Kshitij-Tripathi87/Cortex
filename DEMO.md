# Cortex Demo Script

A 5-minute live walkthrough of the Cortex Morning Brief for a design-partner audience.
Every step has a single, defensible screen to show.

---

## Pre-demo setup (run once, 60s)

```bash
# Terminal 1 - backend
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 - frontend
cd frontend
npm run dev
```

Open <http://localhost:3000/mvp>.

Have ready:
- The 2 UUIDs from `seed_ids.json` (workspace + supplier `aaaaaaa1-...`)
- This tab open in a second window: <http://localhost:8000/docs>

---

## Beat 1 — Frame the problem (30s)

> "Mid-market manufacturers are losing six figures per supplier disruption, and the
> decision cycle takes three days because the data lives in five systems."

Say, don't show:
- Decisions today are made in spreadsheets + email.
- Finance needs a number, ops needs a sequence, the buyer needs a phone call.
- Cortex collapses that to **one screen, one decision, deterministic math**.

Show: the empty `Morning Brief` page with the four role tabs visible.

---

## Beat 2 — Generate the brief (45s)

1. Paste the workspace UUID.
2. Paste the supplier UUID.
3. Click **Supplier fails**.

Watch for:
- The brief appears in under 2s.
- The impact score, blast radius, and timeline populate.
- No spinners that hang. No "AI thinking" copy. Determinism is the feature.

Talking point:
> "Every number on this screen is reproducible. Same inputs, same numbers, every time.
> There is no LLM in this loop."

---

## Beat 3 — Read the CFO view (60s)

Click the **CFO** role.

Walk the screen top-to-bottom:
- **Critical Alert Card** — `Impact Score`, severity tier, `Decision Deadline`.
- **Business Impact** — revenue/margin risk, penalty exposure, working-capital tie.
- **Timeline** — when each component stocks out, ordered by hour.
- **Recommendations** — ranked by `net_benefit`, not gut.
- **Evidence** — direct traceability back to the supply-chain graph.
- **Decision Confidence** — five deterministic sub-scores, no "AI trust".

Click the **Scoring Formula** disclosure. Read one line aloud:
> "This is the formula. You can audit it. You can fork it."

---

## Beat 4 — Flip the role (45s)

Click **COO**. The page reorders — operational impact now sits above the financial
detail. Click **Logistics**. The timeline rises. Click **Procurement**. The
recommendations rise.

Talking point:
> "The same brief, the same numbers. The role switch just changes the order
> of the page. The math doesn't move."

This is the moment a buyer signs: the tool respects *who* they are without
showing them *different* facts.

---

## Beat 5 — Drill into evidence (45s)

Open the **Evidence** drawer. Click `Orders at risk`.

Show:
- The order IDs, customer IDs, quantities.
- These are pulled directly from the synthetic dataset — no magic, no joins to chase.

Then open the **Decision Confidence** disclosure. Read the formula.

> "We do not hide the model. We print it on the page."

---

## Beat 6 — Show the backtest (45s)

In a third terminal:

```bash
cd backend
python scripts/run_backtest.py --scenario supplier_delay
```

Output:

```
Accuracy : 1.0000
Precision: 1.0000
Recall   : 1.0000
F1       : 1.0000
TP=9 FP=0 FN=0
```

Talking point:
> "We don't claim accuracy on a curated slide. We claim accuracy on a known
> ground-truth scenario with held-out entities. The math was right; the
> numbers are reproducible; the audit is open."

---

## Beat 7 — Close (30s)

Two sentences. No more.

> "One screen, one decision, deterministic math. The brief your CFO trusts
> is the same brief your buyer acts on."

Ask one question: *"Where in your org does this replace a meeting?"*

Then stop talking.

---

## Anti-patterns (do not do)

- Do not call it "AI".
- Do not demo without seeded data — cold loads look broken.
- Do not open the OpenAPI page during the demo unless asked.
- Do not promise multi-source connectors in the MVP. CSV is the contract.
- Do not edit the formula on stage. The freeze is the feature.

---

## Failure recovery

| Symptom | Fix |
| --- | --- |
| Brief won't load | Check backend on `:8000`; UUIDs from `seed_ids.json` |
| Frontend 404 on `/mvp` | `npm run dev` and use port 3000 |
| Backtest fails | `pytest tests/test_mvp_engines.py -q` to isolate |
| tsc errors | `npm run typecheck` in `frontend/` |
