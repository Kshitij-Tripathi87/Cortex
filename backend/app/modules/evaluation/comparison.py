"""Engine Comparison — Compare multiple engines on the same dataset."""

from __future__ import annotations

from uuid import uuid4

from app.modules.evaluation.models import (
    EngineComparison,
)


class EngineComparator:
    """Compares multiple engines on the same dataset."""

    def __init__(self):
        self.comparisons: list[EngineComparison] = []

    def compare(
        self,
        baseline_engine: str,
        baseline_version: str,
        candidate_engines: list[dict],  # [{"engine_type": str, "version": str, "results": dict}]
        dataset_id: str,
        dataset_version: int,
    ) -> EngineComparison:
        """Compare baseline engine against candidates."""
        baseline_results = None
        for c in candidate_engines:
            if c["engine_type"] == baseline_engine and c.get("version") == baseline_version:
                baseline_results = c.get("results", {})
                break

        if not baseline_results:
            raise ValueError("Baseline engine results not found in candidates")

        comparison_results = {}
        for candidate in candidate_engines:
            if (
                candidate["engine_type"] == baseline_engine
                and candidate.get("version") == baseline_version
            ):
                continue

            cand_results = candidate.get("results", {})
            comparison = self._compare_results(baseline_results, cand_results, candidate)
            comparison_results[
                candidate["engine_type"] + "_" + (candidate.get("version", "latest"))
            ] = comparison

        # Determine winner
        winner = self._determine_winner(baseline_results, candidate_engines)

        comparison = EngineComparison(
            comparison_id=uuid4(),
            baseline_engine=baseline_engine,
            baseline_version=baseline_version,
            candidate_engines=[
                {"engine_type": c["engine_type"], "version": c.get("version")}
                for c in candidate_engines
            ],
            dataset_id="",  # filled by caller
            dataset_version=dataset_version,
            results=comparison_results,
            winner=winner,
        )
        self.comparisons.append(comparison)
        return comparison

    def _compare_results(self, baseline: dict, candidate: dict, candidate_info: dict) -> dict:
        """Compare two sets of aggregate metrics."""
        baseline_metrics = baseline.get("aggregate_metrics", {})
        candidate_metrics = candidate.get("aggregate_metrics", {})

        comparison = {}
        set(baseline_metrics.keys()) | set(candidate_metrics.keys())

        wins = 0
        losses = 0
        ties = 0

        for key in set(baseline_metrics.keys()) | set(candidate_metrics.keys()):
            base_val = baseline_metrics.get(key)
            cand_val = candidate_metrics.get(key)

            if base_val is None or cand_val is None:
                comparison[key] = {
                    "baseline": base_val,
                    "candidate": candidate.get("candidate_val"),
                    "verdict": "incomplete",
                }
                continue

            candidate_metrics[key] - baseline_metrics[key]

            # Determine if higher is better (most metrics) or lower is better (error metrics)
            higher_is_better = not any(
                k in key.lower() for k in ["error", "mae", "mape", "ece", "mce", "brier", "latency"]
            )

            if higher_is_better:
                better = (
                    "candidate" if candidate_metrics[key] > baseline_metrics[key] else "baseline"
                )
            else:
                better = (
                    "candidate" if candidate_metrics[key] < baseline_metrics[key] else "baseline"
                )

            if better == "candidate":
                wins += 1
            elif better == "baseline":
                losses += 1
            else:
                ties += 1

            comparison[key] = {
                "baseline": baseline_metrics[key],
                "candidate": candidate_metrics[key],
                "difference": candidate_metrics[key] - baseline_metrics[key],
                "percent_change": (
                    (candidate_metrics[key] - baseline_metrics[key]) / baseline_metrics[key] * 100
                )
                if baseline_metrics[key] != 0
                else float("inf"),
                "better": better,
            }

        return {
            "candidate_engine": candidate.get("engine_type"),
            "candidate_version": candidate.get("version"),
            "metrics_comparison": comparison,
            "wins": wins,
            "losses": losses,
            "ties": ties,
        }

    def _determine_winner(self, baseline: dict, candidates: list) -> str:
        """Determine overall winner based on key metrics."""
        # Key metrics where higher is better
        positive_metrics = ["component_f1", "product_f1", "recommendation_rank_agreement"]
        # Key metrics where lower is better
        negative_metrics = [
            "revenue_mae",
            "revenue_mape",
            "deadline_mae",
            "calibration_ece",
            "brier_score",
        ]

        scores = {}
        for cand in [
            {"engine_type": "baseline", "version": "baseline", "results": baseline}
        ] + candidates:
            key = cand["engine_type"] + "_" + cand.get("version", "latest")
            score = 0
            results = cand.get("results", {})
            agg = results.get("aggregate_metrics", {})

            for metric in positive_metrics:
                if metric in agg:
                    score += agg[metric]
            for metric in negative_metrics:
                if metric in agg:
                    score -= agg[metric]

            scores[key] = score

        if not scores:
            return "tie"

        best = max(scores, key=scores.get)
        return best


def generate_comparison_report(comparison: dict) -> dict:
    """Generate a human-readable comparison report."""
    lines = []
    lines.append("=" * 60)
    lines.append("ENGINE COMPARISON REPORT")
    lines.append("=" * 60)

    for candidate_key, comp in comparison.items():
        if candidate_key == "baseline":
            continue

        lines.append(f"\nCandidate: {comp.get('candidate_engine', 'Unknown')}")
        lines.append(f"Version: {comp.get('candidate_version', 'Unknown')}")
        lines.append(
            f"Wins: {comp.get('wins', 0)}, Losses: {comp.get('losses', 0)}, Ties: {comp.get('ties', 0)}"
        )
        lines.append("-" * 40)

        for metric, details in comp.get("metrics_comparison", {}).items():
            baseline = details.get("baseline")
            candidate = details.get("candidate")
            diff = details.get("difference")
            pct = details.get("percent_change")
            better = details.get("better")

            if baseline is not None and candidate is not None:
                lines.append(
                    f"  {metric}: baseline={baseline:.4f}, candidate={candidate:.4f}, "
                    f"diff={diff:+.4f} ({pct:+.2f}%), better={better}"
                )

    return "\n".join(lines)


def statistical_significance(
    baseline_samples: list[float],
    candidate_samples: list[float],
    alpha: float = 0.05,
) -> dict:
    """Compute statistical significance using t-test (requires scipy)."""
    try:
        from scipy import stats

        stat, p_value = stats.ttest_ind(candidate_samples, baseline_samples, equal_var=False)
        return {
            "t_statistic": stat,
            "p_value": p_value,
            "significant": p_value < alpha,
            "alpha": alpha,
        }
    except ImportError:
        return {
            "error": "scipy not installed",
            "significant": None,
        }


def paired_significance(
    baseline_samples: list[float],
    candidate_samples: list[float],
    alpha: float = 0.05,
) -> dict:
    """Paired t-test for paired samples (same scenarios)."""
    try:
        from scipy import stats

        stat, p_value = stats.ttest_rel(candidate_samples, baseline_samples)
        return {
            "t_statistic": stat,
            "p_value": p_value,
            "significant": p_value < alpha,
            "alpha": alpha,
        }
    except ImportError:
        return {
            "error": "scipy not installed",
            "significant": None,
        }


def wilcoxon_test(
    baseline_samples: list[float], candidate_samples: list[float], alpha: float = 0.05
) -> dict:
    """Wilcoxon signed-rank test (non-parametric alternative to paired t-test)."""
    try:
        from scipy import stats

        stat, p_value = stats.wilcoxon(candidate_samples, baseline_samples, alternative="greater")
        return {
            "statistic": stat,
            "p_value": p_value,
            "significant": p_value < alpha,
            "alpha": alpha,
        }
    except ImportError:
        return {
            "error": "scipy not installed",
            "significant": None,
        }


__all__ = [
    "EngineComparator",
    "generate_comparison_report",
    "statistical_significance",
    "paired_significance",
    "wilcoxon_test",
]
