"""Metrics Calculator — Computes evaluation metrics."""

from __future__ import annotations

import math


def precision_recall_f1(gt_set: set, pred_set: set) -> tuple[float, float, float]:
    """Compute precision, recall, F1 for two sets."""
    if not gt_set and not pred_set:
        return 1.0, 1.0, 1.0
    if not gt_set or not pred_set:
        return 0.0, 0.0, 0.0

    tp = len(gt_set & pred_set)
    fp = len(pred_set - gt_set)
    fn = len(gt_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return precision, recall, f1


def exact_match(gt_set: set, pred_set: set) -> bool:
    """Check if two sets are exactly equal."""
    return gt_set == pred_set


def mae(gt_values: list[float], pred_values: list[float]) -> float:
    """Mean Absolute Error."""
    if not gt_values or len(gt_values) != len(pred_values):
        return 0.0
    return sum(abs(g - p) for g, p in zip(gt_values, pred_values)) / len(gt_values)


def mape(gt_values: list[float], pred_values: list[float]) -> float:
    """Mean Absolute Percentage Error."""
    if not gt_values or len(gt_values) != len(pred_values):
        return 0.0
    total = 0.0
    count = 0
    for g, p in zip(gt_values, pred_values):
        if g != 0:
            total += abs(g - p) / abs(g)
            count += 1
    return total / count if count > 0 else 0.0


def rmse(gt_values: list[float], pred_values: list[float]) -> float:
    """Root Mean Square Error."""
    if not gt_values or len(gt_values) != len(pred_values):
        return 0.0
    return math.sqrt(sum((g - p) ** 2 for g, p in zip(gt_values, pred_values)) / len(gt_values))


def calibration_ece(gt_probs: list[float], pred_probs: list[float], n_bins: int = 10) -> float:
    """Expected Calibration Error (ECE)."""
    if len(gt_probs) != len(pred_probs) or not gt_probs:
        return 0.0

    bins = [[] for _ in range(n_bins)]
    for gt, pred in zip(gt_probs, pred_probs):
        bin_idx = min(int(pred * n_bins), n_bins - 1)
        bins[bin_idx].append((gt, pred))

    ece = 0.0
    total = len(gt_probs)
    for bin_samples in bins:
        if not bin_samples:
            continue
        bin_accuracy = sum(gt for gt, _ in bin_samples) / len(bin_samples)
        bin_confidence = sum(pred for _, pred in bin_samples) / len(bin_samples)
        ece += (len(bin_samples) / total) * abs(bin_accuracy - bin_confidence)

    return ece


def mce(gt_probs: list[float], pred_probs: list[float], n_bins: int = 10) -> float:
    """Maximum Calibration Error (MCE)."""
    if len(gt_probs) != len(pred_probs) or not gt_probs:
        return 0.0

    bins = [[] for _ in range(n_bins)]
    for gt, pred in zip(gt_probs, pred_probs):
        bin_idx = min(int(pred * n_bins), n_bins - 1)
        bins[bin_idx].append((gt, pred))

    max_error = 0.0
    for bin_samples in bins:
        if not bin_samples:
            continue
        bin_accuracy = sum(gt for gt, _ in bin_samples) / len(bin_samples)
        bin_confidence = sum(pred for _, pred in bin_samples) / len(bin_samples)
        max_error = max(max_error, abs(bin_accuracy - bin_confidence))

    return max_error


def brier_score(gt_probs: list[float], outcomes: list[int]) -> float:
    """Brier Score for probabilistic predictions."""
    if len(gt_probs) != len(outcomes) or not gt_probs:
        return 0.0
    return sum((p - o) ** 2 for p, o in zip(gt_probs, outcomes)) / len(gt_probs)


def reliability_diagram(gt_probs: list[float], outcomes: list[int], n_bins: int = 10) -> list[dict]:
    """Generate reliability diagram data points."""
    if len(gt_probs) != len(outcomes) or not gt_probs:
        return []

    bins = [[] for _ in range(n_bins)]
    for prob, outcome in zip(gt_probs, outcomes):
        bin_idx = min(int(prob * n_bins), n_bins - 1)
        bins[bin_idx].append((prob, outcome))

    points = []
    for i, bin_samples in enumerate(bins):
        if not bin_samples:
            points.append({
                "bin": i,
                "confidence": (i + 0.5) / n_bins,
                "accuracy": 0.0,
                "count": 0,
            })
            continue

        avg_confidence = sum(p for p, _ in bin_samples) / len(bin_samples)
        accuracy = sum(o for _, o in bin_samples) / len(bin_samples)
        points.append({
            "bin": i,
            "confidence": avg_confidence,
            "accuracy": accuracy,
            "count": len(bin_samples),
        })

    return points


def ndcg_at_k(gt_relevance: list[float], pred_scores: list[float], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k."""
    if not gt_relevance or not pred_scores:
        return 0.0

    # Sort by predicted scores
    pairs = sorted(zip(pred_scores, gt_relevance), key=lambda x: x[0], reverse=True)
    dcg = 0.0
    for i, (_, rel) in enumerate(pairs[:k]):
        dcg += rel / math.log2(i + 2)

    # Ideal DCG
    ideal = sorted(gt_relevance, reverse=True)
    idcg = 0.0
    for i, rel in enumerate(ideal[:k]):
        idcg += rel / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


def mrr(gt_ranks: list[int], pred_ranks: list[int]) -> float:
    """Mean Reciprocal Rank."""
    if not gt_ranks or not pred_ranks:
        return 0.0

    reciprocal_ranks = []
    for gt_rank, pred_rank in zip(gt_ranks, pred_ranks):
        if pred_rank > 0:
            reciprocal_ranks.append(1.0 / pred_rank)
        else:
            reciprocal_ranks.append(0.0)

    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0


def kendall_tau(gt_ranking: list, pred_ranking: list) -> float:
    """Kendall's tau rank correlation."""
    if len(gt_ranking) != len(pred_ranking) or not gt_ranking:
        return 0.0

    # Map items to ranks
    gt_rank_map = {item: i for i, item in enumerate(gt_ranking)}
    pred_rank_map = {item: i for i, item in enumerate(pred_ranking)}

    concordant = 0
    discordant = 0
    n = len(gt_ranking)

    for i in range(n):
        for j in range(i + 1, n):
            item_i = gt_ranking[i]
            item_j = gt_ranking[j]
            if item_i in pred_rank_map and item_j in pred_rank_map:
                gt_order = gt_rank_map[item_i] < gt_rank_map[item_j]
                pred_order = pred_rank_map[item_i] < pred_rank_map[item_j]
                if gt_order == pred_order:
                    concordant += 1
                else:
                    discordant += 1

    total = concordant + discordant
    return (concordant - discordant) / total if total > 0 else 0.0


def spearman_rho(gt_ranking: list, pred_ranking: list) -> float:
    """Spearman's rank correlation coefficient."""
    if len(gt_ranking) != len(pred_ranking) or not gt_ranking:
        return 0.0

    gt_rank_map = {item: i + 1 for i, item in enumerate(gt_ranking)}
    pred_rank_map = {item: i + 1 for i, item in enumerate(pred_ranking)}

    items = set(gt_ranking) & set(pred_ranking)
    if not items:
        return 0.0

    n = len(items)
    sum_d2 = sum((gt_rank_map[i] - pred_rank_map[i]) ** 2 for i in items)

    return 1 - (6 * sum_d2) / (n * (n**2 - 1))


def average_precision(gt_set: set, pred_ranked: list) -> float:
    """Average Precision for a single query."""
    if not gt_set or not pred_ranked:
        return 0.0

    hits = 0
    ap = 0.0
    for i, item in enumerate(pred_ranked):
        if item in gt_set:
            hits += 1
            ap += hits / (i + 1)
    return ap / len(gt_set) if gt_set else 0.0


def mean_average_precision(gt_sets: list[set], pred_ranked_lists: list[list]) -> float:
    """Mean Average Precision across queries."""
    if not gt_sets or not pred_ranked_lists:
        return 0.0
    return sum(average_precision(gt, pred) for gt, pred in zip(gt_sets, pred_ranked_lists)) / len(gt_sets)


def recommendation_rank_agreement(gt_ranking: list, pred_ranking: list) -> float:
    """Agreement between ground truth and predicted recommendation rankings."""
    if not gt_ranking or not pred_ranking:
        return 0.0

    # Compute overlap in top-k
    k = min(len(gt_ranking), len(pred_ranking))
    gt_top = set(gt_ranking[:k])
    pred_top = set(pred_ranking[:k])

    overlap = len(gt_top & pred_top)
    return overlap / k if k > 0 else 0.0


def timeline_error(gt_events: list[dict], pred_events: list[dict]) -> float:
    """Mean absolute error in timeline event hours."""
    # Match events by title/description
    gt_by_title = {e.get("title", ""): e.get("hour", 0) for e in gt_events}
    pred_by_title = {e.get("title", ""): e.get("hour", 0) for e in pred_events}

    common_titles = set(gt_by_title.keys()) & set(pred_by_title.keys())
    if not common_titles:
        return 0.0

    errors = [abs(gt_by_title[t] - pred_by_title[t]) for t in common_titles]
    return sum(errors) / len(errors)


def confidence_interval(data: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Compute confidence interval for a list of values."""
    if not data:
        return (0.0, 0.0)
    n = len(data)
    mean = sum(data) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in data) / (n - 1)) if n > 1 else 0.0
    z = 1.96 if confidence == 0.95 else 2.576  # 95% or 99%
    margin = z * std / math.sqrt(n)
    return (mean - margin, mean + margin)


def bootstrap_ci(data: list[float], n_bootstrap: int = 1000, confidence: float = 0.95) -> tuple[float, float]:
    """Bootstrap confidence interval."""
    if not data:
        return (0.0, 0.0)
    import random
    bootstrapped = []
    for _ in range(n_bootstrap):
        sample = [random.choice(data) for _ in data]
        bootstrapped.append(sum(sample) / len(sample))
    bootstrapped.sort()
    alpha = (1 - confidence) / 2
    lower = bootstrapped[int(alpha * n_bootstrap)]
    upper = bootstrapped[int((1 - alpha) * n_bootstrap)]
    return (lower, upper)


__all__ = [
    "precision_recall_f1",
    "exact_match",
    "mae",
    "mape",
    "rmse",
    "calibration_ece",
    "mce",
    "brier_score",
    "reliability_diagram",
    "ndcg_at_k",
    "mrr",
    "kendall_tau",
    "spearman_rho",
    "average_precision",
    "mean_average_precision",
    "recommendation_rank_agreement",
    "timeline_error",
    "confidence_interval",
    "bootstrap_ci",
]
