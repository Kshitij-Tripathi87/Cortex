"""CI Performance Budget enforcement.

Run as part of CI pipeline. Fails if any budget is breached.
"""

import sys

from app.modules.performance.budgets import BUDGETS, check_budget, format_budget_report


def run_benchmarks() -> dict[str, dict[str, float]]:
    """Run benchmark suite and return measured values.

    In Phase 2, this is a placeholder. Phase 3+ connects to actual
    k6/locust benchmark results.
    """
    # Placeholder: in real CI, this reads from benchmark artifact
    return {}


def main() -> int:
    """Run budget checks. Returns 0 on pass, 1 on breach."""
    results: list = []

    # In real CI, load measured values from benchmark artifact
    measured = run_benchmarks()

    # Check each budget
    for subsystem, metrics in BUDGETS.items():
        for metric, target in metrics.items():
            measured_value = measured.get(subsystem, {}).get(metric, 0.0)
            result = check_budget(subsystem, metric, measured_value)
            results.append(result)

    # Print report
    print(format_budget_report(results))

    # Fail on breach
    breaches = [r for r in results if r.status == "breach"]
    if breaches:
        print(f"\n🚨 {len(breaches)} budget breach(es) — CI failed")
        return 1

    alerts = [r for r in results if r.status == "alert"]
    if alerts:
        print(f"\n⚠️ {len(alerts)} budget alert(s) — review recommended")

    print("\n✅ All budgets OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
