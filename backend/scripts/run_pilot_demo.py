"""Run Enterprise Pilot Demonstration Script.

Usage:
  python scripts/run_pilot_demo.py

Executes the complete 8-stage operational pilot walkthrough showcasing:
- Real-world supplier disruption (Apex Mobility Global)
- Minimal enterprise CSV/table ingestion
- GNN risk propagation & critical path analysis
- Multi-agent specialist consensus synthesis
- Policy engine & L3 autonomy checks
- Digital twin simulation dry-run
- Human decision briefing card
- Idempotent ERP adapter dispatch
- Outcome capture & Net Economic Value Created
"""

import os
import sys

# Add backend to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.modules.production_validation.pilot_demo_harness import (
    EnterprisePilotDemoHarness,
)


def main() -> None:
    print("=" * 80)
    print(" CORTEX NEXUS — ENTERPRISE OPERATIONAL DECISION & EXECUTION PLATFORM ")
    print("=" * 80)
    print("Product:       Cortex Nexus (Operational Decision System)")
    print("Customer:      Apex Mobility Global (EV Manufacturer)")
    print("Incident:      SiliconPower Fab 4 Microcontroller Supply Delay (12 Days)")
    print("Objective:     Prevent Detroit EV Assembly Line Shutdown")
    print("-" * 80)

    harness = EnterprisePilotDemoHarness()
    report = harness.run_demo()

    for stage in report.stages:
        print(f"\n[STAGE {stage.stage_number}] {stage.stage_name}")
        print(f"  Summary: {stage.headline}")
        print("  Key Metrics:")
        for k, v in stage.key_metrics.items():
            print(f"    • {k}: {v}")
        print("  Operational Details:")
        for d in stage.details:
            print(f"    - {d}")

    print("\n" + "=" * 80)
    print(" CORTEX NEXUS — DECISION LIFECYCLE SUMMARY ")
    print("=" * 80)
    dec = report.final_decision_lifecycle
    print(f"  Decision ID:           {dec.decision_id}")
    print(f"  Incident Description:  {dec.incident_description}")
    print(f"  Revenue at Risk:       ${dec.revenue_at_risk_usd:,.2f}")
    print(f"  Hours to 1st Stockout: {dec.hours_to_first_stockout:.1f} hrs")
    print(
        f"  Recommended Action:    {dec.recommended_action.action_type.value} -> {dec.recommended_action.entity_id}"
    )
    print(f"  Consensus Score:       {dec.agent_consensus_score:.4f}")
    print(f"  Policy Status:         {dec.policy_status}")
    print(f"  Autonomy Level:        {dec.autonomy_level.name}")
    print(f"  Operator Decision:     {dec.operator_decision.value.upper()} (by {dec.operator_id})")
    print(
        f"  Execution External TX: {dec.execution_result.external_transaction_id if dec.execution_result else 'N/A'}"
    )
    print(f"  Actual Protected Rev:  ${dec.actual_revenue_protected_usd:,.2f}")
    print(f"  Intervention Cost:     ${dec.intervention_cost_usd:,.2f}")
    print(f"  NET ECONOMIC VALUE:    ${dec.net_economic_value_created_usd:,.2f}")
    print(f"  Prediction Error:      {dec.prediction_error_pct:.2f}%")
    print("=" * 80)
    print(" PILOT DEMONSTRATION COMPLETE: 100% SUCCESS ")
    print("=" * 80)


if __name__ == "__main__":
    main()
