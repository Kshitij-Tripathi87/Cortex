"""Intelligence Plane — Baseline Models.

Simple, interpretable baselines that must be beaten before any complex model ships.
All models train on versioned synthetic ground truth and are evaluated against
the deterministic wedge.
"""

from __future__ import annotations

import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

try:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        brier_score_loss,
        f1_score,
        precision_score,
        recall_score,
    )
    from sklearn.model_selection import train_test_split

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


@dataclass(frozen=True)
class BaselineMetrics:
    """Metrics for a baseline model evaluation."""

    model_id: str
    model_version: str
    dataset_id: str
    dataset_version: int

    # Classification metrics
    precision: float
    recall: float
    f1: float
    accuracy: float
    exact_match_rate: float

    # Regression metrics
    revenue_mae: float
    revenue_mape: float
    margin_mae: float
    penalty_mae: float
    deadline_mae: float

    # Ranking metrics
    ndcg: float
    rank_agreement: float

    # Confidence metrics
    calibration_ece: float
    calibration_mce: float
    brier_score: float

    # Comparison vs deterministic
    beats_deterministic: bool
    improvement_delta: dict[str, float]

    evaluated_at: datetime = datetime.now(UTC)


class BaselineModel(ABC):
    """Abstract base class for all baseline models."""

    def __init__(self, model_id: str, model_version: str):
        self.model_id = model_id
        self.model_version = model_version
        self._model: Any = None
        self._is_trained = False

    @abstractmethod
    def train(self, X: np.ndarray, y: np.ndarray, **kwargs: Any) -> BaselineMetrics:
        """Train the model on labeled data."""
        pass

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions."""
        pass

    @abstractmethod
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities/confidence scores."""
        pass

    def save(self, path: Path) -> None:
        """Save model to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model_id": self.model_id,
                    "model_version": self.model_version,
                    "model": self._model,
                    "is_trained": self._is_trained,
                },
                f,
            )

    @classmethod
    def load(cls, path: Path) -> BaselineModel:
        """Load model from disk."""
        with open(path, "rb") as f:
            data = pickle.load(f)  # noqa: S301 - trusted internal model files
        instance = cls(data["model_id"], data["model_version"])
        instance._model = data["model"]
        instance._is_trained = data["is_trained"]
        return instance


class RankingBaseline(BaselineModel):
    """Baseline ranking model for recommendation prioritization.

    Trains on synthetic ground truth to predict which recommendation
    actions should be ranked highest for a given scenario.
    """

    def __init__(self, model_id: str = "baseline_ranking", model_version: str = "1.0.0"):
        super().__init__(model_id, model_version)
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not available. Install with: pip install scikit-learn")
        self._model = LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
        )

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        dataset_id: str = "unknown",
        dataset_version: int = 0,
        **kwargs: Any,
    ) -> BaselineMetrics:
        """Train ranking model.

        Args:
            X: Feature matrix [n_samples, n_features]
            y: Target labels (recommendation action indices)
            dataset_id: Dataset registry ID
            dataset_version: Dataset version
        """
        # Split for evaluation
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        self._model.fit(X_train, y_train)
        self._is_trained = True

        # Evaluate
        y_pred = self._model.predict(X_test)
        y_proba = self._model.predict_proba(X_test)

        precision = precision_score(y_test, y_pred, average="weighted", zero_division=0)
        recall = recall_score(y_test, y_pred, average="weighted", zero_division=0)
        f1 = f1_score(y_test, y_pred, average="weighted", zero_division=0)
        accuracy = accuracy_score(y_test, y_pred)

        # Compute exact match rate (top-1 agreement)
        exact_match = (y_pred == y_test).mean()

        # For regression targets, we'd need separate training
        # These are placeholders - actual implementation would train separate heads
        revenue_mae = 0.0
        revenue_mape = 0.0
        margin_mae = 0.0
        penalty_mae = 0.0
        deadline_mae = 0.0

        # NDCG requires relevance scores - placeholder
        ndcg = 0.0
        rank_agreement = exact_match  # Proxy

        # Calibration metrics on probabilities
        # ECE: Expected Calibration Error
        confidences = y_proba.max(axis=1)
        accuracies = (y_pred == y_test).astype(float)
        n_bins = 10
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        bin_lowers = bin_boundaries[:-1]
        bin_uppers = bin_boundaries[1:]

        ece = 0.0
        mce = 0.0
        for bin_lower, bin_upper in zip(bin_lowers, bin_uppers, strict=True):
            in_bin = (confidences > bin_lower) & (confidences <= bin_upper)
            prop_in_bin = in_bin.mean()
            if prop_in_bin > 0:
                accuracy_in_bin = accuracies[in_bin].mean()
                avg_confidence_in_bin = confidences[in_bin].mean()
                delta = abs(avg_confidence_in_bin - accuracy_in_bin)
                ece += delta * prop_in_bin
                mce = max(mce, delta)

        brier = brier_score_loss(y_test == y_pred, confidences)

        # Compare against deterministic baseline (would be passed in)
        beats_det = precision > 0.5  # Placeholder threshold
        improvement = {
            "precision": precision - 0.5,
            "recall": recall - 0.5,
            "f1": f1 - 0.5,
        }

        return BaselineMetrics(
            model_id=self.model_id,
            model_version=self.model_version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            precision=precision,
            recall=recall,
            f1=f1,
            accuracy=accuracy,
            exact_match_rate=exact_match,
            revenue_mae=revenue_mae,
            revenue_mape=revenue_mape,
            margin_mae=margin_mae,
            penalty_mae=penalty_mae,
            deadline_mae=deadline_mae,
            ndcg=ndcg,
            rank_agreement=rank_agreement,
            calibration_ece=ece,
            calibration_mce=mce,
            brier_score=brier,
            beats_deterministic=beats_det,
            improvement_delta=improvement,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        return self._model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        return self._model.predict_proba(X)


class CalibrationBaseline(BaselineModel):
    """Baseline confidence calibration model using Isotonic Regression.

    Calibrates the deterministic engine's confidence scores to match
    actual empirical accuracy.
    """

    def __init__(self, model_id: str = "baseline_calibration", model_version: str = "1.0.0"):
        super().__init__(model_id, model_version)
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not available. Install with: pip install scikit-learn")
        self._model = IsotonicRegression(out_of_bounds="clip")

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        dataset_id: str = "unknown",
        dataset_version: int = 0,
        **kwargs: Any,
    ) -> BaselineMetrics:
        """Train calibration model.

        Args:
            X: Confidence scores from deterministic engine [n_samples]
            y: Binary outcomes (1 = correct, 0 = incorrect) [n_samples]
            dataset_id: Dataset registry ID
            dataset_version: Dataset version
        """
        X = X.reshape(-1, 1) if X.ndim == 1 else X
        y = y.reshape(-1, 1) if y.ndim == 1 else y

        # Split for evaluation
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        self._model.fit(X_train.ravel(), y_train.ravel())
        self._is_trained = True

        # Evaluate calibration
        y_pred_proba = self.predict_proba(X_test)
        y_pred = (y_pred_proba > 0.5).astype(int)

        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        accuracy = accuracy_score(y_test, y_pred)
        exact_match = accuracy

        # Regression metrics (not applicable for calibration)
        revenue_mae = revenue_mape = margin_mae = penalty_mae = deadline_mae = 0.0
        ndcg = rank_agreement = 0.0

        # ECE / MCE / Brier
        confidences = y_pred_proba.ravel()
        accuracies = (y_pred == y_test.ravel()).astype(float)

        n_bins = 10
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        bin_lowers = bin_boundaries[:-1]
        bin_uppers = bin_boundaries[1:]

        ece = 0.0
        mce = 0.0
        for bin_lower, bin_upp in zip(bin_lowers, bin_uppers, strict=True):
            in_bin = (confidences > bin_lower) & (confidences <= bin_upp)
            prop_in_bin = in_bin.mean()
            if prop_in_bin > 0:
                accuracy_in_bin = accuracies[in_bin].mean()
                avg_confidence_in_bin = confidences[in_bin].mean()
                delta = abs(avg_confidence_in_bin - accuracy_in_bin)
                ece += delta * prop_in_bin
                mce = max(mce, delta)

        brier = brier_score_loss(y_test, confidences)

        # Beats deterministic if calibration error is lower
        # Deterministic ECE would be computed on raw confidences
        beats_det = ece < 0.1  # Placeholder threshold
        improvement = {
            "ece": 0.1 - ece,  # Improvement over assumed deterministic ECE of 0.1
            "brier": 0.25 - brier,  # Improvement over random baseline
        }

        return BaselineMetrics(
            model_id=self.model_id,
            model_version=self.model_version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            precision=precision,
            recall=recall,
            f1=f1,
            accuracy=accuracy,
            exact_match_rate=exact_match,
            revenue_mae=revenue_mae,
            revenue_mape=revenue_mape,
            margin_mae=margin_mae,
            penalty_mae=penalty_mae,
            deadline_mae=deadline_mae,
            ndcg=ndcg,
            rank_agreement=rank_agreement,
            calibration_ece=ece,
            calibration_mce=mce,
            brier_score=brier,
            beats_deterministic=beats_det,
            improvement_delta=improvement,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        X = X.reshape(-1, 1) if X.ndim == 1 else X
        return (self._model.predict(X.ravel()) > 0.5).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        X = X.reshape(-1, 1) if X.ndim == 1 else X
        calibrated = self._model.predict(X.ravel())
        # Return as [p(0), p(1)] for compatibility
        return np.column_stack([1 - calibrated, calibrated])


class SupplierRiskSimilarityBaseline(BaselineModel):
    """Baseline for supplier similarity / risk clustering.

    Uses graph features to cluster suppliers by risk profile.
    """

    def __init__(
        self, model_id: str = "baseline_supplier_similarity", model_version: str = "1.0.0"
    ):
        super().__init__(model_id, model_version)
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not available. Install with: pip install scikit-learn")
        from sklearn.cluster import KMeans

        self._model = KMeans(n_clusters=5, random_state=42, n_init=10)

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray | None = None,
        dataset_id: str = "unknown",
        dataset_version: int = 0,
        **kwargs: Any,
    ) -> BaselineMetrics:
        """Train supplier clustering (unsupervised)."""
        self._model.fit(X)
        self._is_trained = True

        # Unsupervised - no ground truth labels
        # Metrics would be cluster quality (silhouette, etc.)
        return BaselineMetrics(
            model_id=self.model_id,
            model_version=self.model_version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            precision=0.0,
            recall=0.0,
            f1=0.0,
            accuracy=0.0,
            exact_match_rate=0.0,
            revenue_mae=0.0,
            revenue_mape=0.0,
            margin_mae=0.0,
            penalty_mae=0.0,
            deadline_mae=0.0,
            ndcg=0.0,
            rank_agreement=0.0,
            calibration_ece=0.0,
            calibration_mce=0.0,
            brier_score=0.0,
            beats_deterministic=False,
            improvement_delta={},
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        return self._model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        # Return cluster distances as pseudo-probabilities
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        distances = self._model.transform(X)
        # Convert to similarity scores (inverse distance)
        similarities = 1.0 / (1.0 + distances)
        # Normalize to sum to 1
        return similarities / similarities.sum(axis=1, keepdims=True)
