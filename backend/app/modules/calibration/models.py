"""Calibration Platform — Confidence calibration and reliability analysis."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.ids import uuid7


class CalibrationMethod(str):
    """Calibration methods."""

    PLATT = "platt"
    ISOTONIC = "isotonic"
    BETA = "beta"
    TEMPERATURE = "temperature"
    DIRICHLET = "dirichlet"


class CalibrationRequest(BaseModel):
    """Request to calibrate a model's confidence."""

    model_id: UUID
    model_version: str
    calibration_method: str = "platt"
    calibration_data: list[dict]  # [{"confidence": float, "correct": int}, ...]
    validation_data: list[dict] | None = None


class CalibrationResult(BaseModel):
    """Result of calibration."""

    calibration_id: UUID = Field(default_factory=uuid7)
    model_id: UUID
    model_version: str
    method: str
    original_ece: float
    calibrated_ece: float
    original_mce: float
    calibrated_mce: float
    brier_score_before: float
    brier_score_after: float
    calibration_params: dict = {}
    calibrated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    validation_metrics: dict | None = None


class CalibrationModel(BaseModel):
    """A fitted calibration model."""

    calibrator_id: UUID = Field(default_factory=uuid7)
    model_id: UUID
    model_version: str
    method: str
    parameters: dict = {}
    fitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    training_ece: float
    training_mce: float
    is_active: bool = True


class CalibrationPlatform:
    """Platform for confidence calibration."""

    def __init__(self):
        self.calibrators: dict[str, Calibrator] = {}
        self.calibration_history: list[CalibrationResult] = {}

    def register_calibrator(self, name: str, calibrator: Calibrator) -> None:
        self.calibrators[name] = calibrator

    async def calibrate(self, request: CalibrationRequest) -> CalibrationResult:
        """Calibrate a model's confidence scores."""
        method = request.calibration_method.lower()

        if method == "platt":
            calibrator = PlattScalingCalibrator()
        elif method == "isotonic":
            calibrator = IsotonicCalibrator()
        elif method == "temperature":
            calibrator = TemperatureScalingCalibrator()
        else:
            raise ValueError(f"Unknown calibration method: {method}")

        # Prepare data
        confidences = [d["confidence"] for d in request.calibration_data]
        labels = [d["correct"] for d in request.calibration_data]

        # Compute original metrics
        original_ece = self._compute_ece(confidences, labels)
        original_mce = self._compute_mce(confidences, labels)
        brier_before = self._brier_score(confidences, labels)

        # Fit calibrator
        calibrator.fit(confidences, labels)

        # Calibrate
        calibrated_confidences = calibrator.predict_proba(confidences)

        # Compute calibrated metrics
        calibrated_ece = self._compute_ece(calibrated_confidences, labels)
        calibrated_mce = self._compute_mce(calibrated_confidences, labels)
        brier_after = self._brier_score(calibrated_confidences, labels)

        # Validate on holdout if provided
        validation_metrics = None
        if request.validation_data:
            val_conf = [d["confidence"] for d in request.validation_data]
            val_labels = [d["correct"] for d in request.validation_data]
            val_calibrated = calibrator.predict_proba(val_conf)
            validation_metrics = {
                "ece": self._compute_ece(val_calibrated, val_labels),
                "mce": self._compute_mce(val_calibrated, val_labels),
                "brier": self._brier_score(val_calibrated, val_labels),
            }

        result = CalibrationResult(
            model_id=request.model_id,
            model_version=request.model_version,
            method=request.calibration_method,
            original_ece=original_ece,
            calibrated_ece=calibrated_ece,
            original_mce=original_mce,
            calibrated_mce=calibrated_mce,
            brier_score_before=brier_before,
            brier_score_after=brier_after,
            calibration_params=calibrator.get_params(),
            validation_metrics=validation_metrics,
        )

        self.calibration_history.append(result)
        return result

    def _compute_ece(self, confidences: list[float], labels: list[int], n_bins: int = 10) -> float:
        """Expected Calibration Error."""
        if not confidences or len(confidences) != len(labels):
            return 0.0

        bins = [[] for _ in range(n_bins)]
        for conf, label in zip(confidences, labels, strict=False):
            bin_idx = min(int(conf * n_bins), n_bins - 1)
            bins[bin_idx].append((conf, label))

        ece = 0.0
        total = len(confidences)
        for bin_samples in bins:
            if not bin_samples:
                continue
            bin_accuracy = sum(label for _, label in bin_samples) / len(bin_samples)
            bin_confidence = sum(conf for conf, _ in bin_samples) / len(bin_samples)
            ece += (len(bin_samples) / total) * abs(bin_accuracy - bin_confidence)
        return ece

    def _compute_mce(self, confidences: list[float], labels: list[int], n_bins: int = 10) -> float:
        """Maximum Calibration Error."""
        if not confidences or len(confidences) != len(labels):
            return 0.0

        bins = [[] for _ in range(n_bins)]
        for conf, label in zip(confidences, labels, strict=False):
            bin_idx = min(int(conf * n_bins), n_bins - 1)
            bins[bin_idx].append((conf, label))

        max_error = 0.0
        for bin_samples in bins:
            if not bin_samples:
                continue
            bin_accuracy = sum(label for _, label in bin_samples) / len(bin_samples)
            bin_confidence = sum(conf for conf, _ in bin_samples) / len(bin_samples)
            max_error = max(max_error, abs(bin_accuracy - bin_confidence))
        return max_error

    def _brier_score(self, confidences: list[float], labels: list[int]) -> float:
        if not confidences or len(confidences) != len(labels):
            return 0.0
        return sum((c - label) ** 2 for c, label in zip(confidences, labels, strict=False)) / len(
            confidences
        )


class Calibrator:
    """Base calibrator class."""

    def fit(self, confidences: list[float], labels: list[int]) -> None:
        raise NotImplementedError

    def predict_proba(self, confidences: list[float]) -> list[float]:
        raise NotImplementedError

    def get_params(self) -> dict:
        return {}


class PlattScalingCalibrator(Calibrator):
    """Platt Scaling calibrator (logistic regression on confidence)."""

    def __init__(self):
        self.a = 0.0
        self.b = 0.0
        self.fitted = False

    def fit(self, confidences: list[float], labels: list[int]) -> None:
        # Simple implementation using gradient descent
        # In production, use scipy.optimize or sklearn

        # Convert to log-odds space
        def sigmoid(x):
            return 1 / (1 + math.exp(-x))

        # Simple gradient descent
        self.a = 1.0
        self.b = 0.0
        lr = 0.01

        for _ in range(1000):
            grad_a = 0.0
            grad_b = 0.0
            for c, y in zip(confidences, labels, strict=False):
                logit = self.a * c + self.b
                p = sigmoid(logit)
                error = p - y
                grad_a += error * c
                grad_b += error

            self.a -= lr * grad_a / len(confidences)
            self.b -= lr * grad_b / len(confidences)

        self.fitted = True

    def predict_proba(self, confidences: list[float]) -> list[float]:
        if not self.fitted:
            return confidences
        import math

        return [1 / (1 + math.exp(-(self.a * c + self.b))) for c in confidences]

    def get_params(self) -> dict:
        return {"a": self.a, "b": self.b, "method": "platt"}


class IsotonicCalibrator(Calibrator):
    """Isotonic regression calibrator."""

    def __init__(self):
        self.boundaries = []
        self.values = []
        self.fitted = False

    def fit(self, confidences: list[float], labels: list[int]) -> None:
        # Simple isotonic regression using PAVA (Pool Adjacent Violators Algorithm)
        pairs = sorted(zip(confidences, labels, strict=False))
        n = len(pairs)

        # Initialize
        y = [p[1] for p in pairs]
        [p[0] for p in pairs]

        # PAVA
        blocks = []
        for i in range(n):
            blocks.append([y[i], 1])  # [sum, count]

        i = 0
        while i < len(blocks) - 1:
            if blocks[i][0] / blocks[i][1] > blocks[i + 1][0] / blocks[i + 1][1]:
                # Pool
                blocks[i][0] += blocks[i + 1][0]
                blocks[i][1] += blocks[i + 1][1]
                blocks.pop(i + 1)
                if i > 0:
                    i -= 1
            else:
                i += 1

        # Expand blocks
        self.boundaries = []
        self.values = []
        idx = 0
        for block_sum, count in blocks:
            val = block_sum / count
            self.values.append(val)
            if idx + count < n:
                self.boundaries.append(pairs[idx + count - 1][0])
            idx += count

        self.fitted = True

    def predict_proba(self, confidences: list[float]) -> list[float]:
        if not self.fitted:
            return confidences

        result = []
        for c in confidences:
            # Find which bin this confidence falls into
            val = self.values[-1]  # default to last
            for i, b in enumerate(self.boundaries):
                if c <= b:
                    val = self.values[i]
                    break
            result.append(val)
        return result

    def get_params(self) -> dict:
        return {"boundaries": self.boundaries, "values": self.values, "method": "isotonic"}


class TemperatureScalingCalibrator(Calibrator):
    """Temperature scaling calibrator (single parameter)."""

    def __init__(self):
        self.temperature = 1.0
        self.fitted = False

    def fit(self, confidences: list[float], labels: list[int]) -> None:
        # Optimize temperature using gradient descent
        import math

        def softmax_with_temp(logits, T):
            scaled = [logit / T for logit in logits]
            max_logit = max(scaled)
            exps = [math.exp(logit - max_logit) for logit in scaled]
            sum_exps = sum(exps)
            return [e / sum_exps for e in exps]

        # Convert confidences to logits
        logits = [math.log(c / (1 - c + 1e-9)) for c in confidences]

        # Simple grid search for temperature
        best_T = 1.0
        best_nll = float("inf")

        for T in [0.1, 0.2, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 5.0, 10.0]:
            nll = 0.0
            for logit, y in zip(logits, labels, strict=False):
                probs = softmax_with_temp([logit], T)
                p = probs[0]
                nll -= y * math.log(p + 1e-9) + (1 - y) * math.log(1 - p + 1e-9)

            if nll < best_nll:
                best_nll = nll
                best_T = T

        self.temperature = best_T
        self.fitted = True

    def predict_proba(self, confidences: list[float]) -> list[float]:
        if not self.fitted:
            return confidences

        import math

        result = []
        for c in confidences:
            logit = math.log(c / (1 - c + 1e-9))
            scaled = logit / self.temperature
            prob = 1 / (1 + math.exp(-scaled))
            result.append(prob)
        return result

    def get_params(self) -> dict:
        return {"temperature": self.temperature, "method": "temperature"}


class CalibrationReport(BaseModel):
    """Calibration report for a model."""

    report_id: UUID = Field(default_factory=uuid7)
    model_id: UUID
    model_version: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Overall metrics
    ece: float
    mce: float
    brier_score: float
    auc_roc: float | None = None
    auc_pr: float | None = None

    # Per-bin details
    reliability_diagram: list[dict] = []

    # Calibration history
    calibration_history: list[dict] = []

    # Recommendations
    needs_calibration: bool = False
    recommended_method: str | None = None


def generate_calibration_report(
    confidences: list[float],
    labels: list[int],
    model_id: UUID,
    model_version: str,
) -> CalibrationReport:
    """Generate a comprehensive calibration report."""
    # Compute metrics
    ece = _compute_ece(confidences, labels)
    mce = _compute_mce(confidences, labels)
    brier = _brier_score(confidences, labels)

    # Reliability diagram
    reliability = _reliability_diagram(confidences, labels)

    needs_cal = ece > 0.05 or mce > 0.1

    recommended = ("isotonic" if ece > 0.1 else "platt") if needs_cal else None

    return CalibrationReport(
        model_id=model_id,
        model_version=model_version,
        ece=ece,
        mce=mce,
        brier_score=brier,
        reliability_diagram=reliability,
        needs_calibration=needs_cal,
        recommended_method=recommended,
    )


def _compute_ece(confidences: list[float], labels: list[int], n_bins: int = 10) -> float:
    if not confidences or len(confidences) != len(labels):
        return 0.0
    bins = [[] for _ in range(n_bins)]
    for c, label in zip(confidences, labels, strict=False):
        idx = min(int(c * n_bins), n_bins - 1)
        bins[idx].append((c, label))

    ece = 0.0
    total = len(confidences)
    for bin_samples in bins:
        if not bin_samples:
            continue
        acc = sum(label for _, label in bin_samples) / len(bin_samples)
        conf = sum(c for c, _ in bin_samples) / len(bin_samples)
        ece += (len(bin_samples) / total) * abs(acc - conf)
    return ece


def _compute_mce(confidences: list[float], labels: list[int], n_bins: int = 10) -> float:
    if not confidences or len(confidences) != len(labels):
        return 0.0
    bins = [[] for _ in range(n_bins)]
    for c, label in zip(confidences, labels, strict=False):
        idx = min(int(c * n_bins), n_bins - 1)
        bins[idx].append((c, label))

    max_err = 0.0
    for bin_samples in bins:
        if not bin_samples:
            continue
        acc = sum(label for _, label in bin_samples) / len(bin_samples)
        conf = sum(c for c, _ in bin_samples) / len(bin_samples)
        max_err = max(max_err, abs(acc - conf))
    return max_err


def _brier_score(confidences: list[float], labels: list[int]) -> float:
    if not confidences or len(confidences) != len(labels):
        return 0.0
    return sum((c - label) ** 2 for c, label in zip(confidences, labels, strict=False)) / len(
        confidences
    )


def _reliability_diagram(
    confidences: list[float], labels: list[int], n_bins: int = 10
) -> list[dict]:
    if not confidences or len(confidences) != len(labels):
        return []

    bins = [[] for _ in range(n_bins)]
    for c, label in zip(confidences, labels, strict=False):
        idx = min(int(c * n_bins), n_bins - 1)
        bins[idx].append((c, label))

    points = []
    for i, bin_samples in enumerate(bins):
        if not bin_samples:
            points.append(
                {
                    "bin": i,
                    "confidence": (i + 0.5) / n_bins,
                    "accuracy": 0.0,
                    "count": 0,
                }
            )
            continue

        avg_conf = sum(c for c, _ in bin_samples) / len(bin_samples)
        accuracy = sum(label for _, label in bin_samples) / len(bin_samples)
        points.append(
            {
                "bin": i,
                "confidence": avg_conf,
                "accuracy": accuracy,
                "count": len(bin_samples),
            }
        )
    return points


__all__ = [
    "CalibrationMethod",
    "CalibrationRequest",
    "CalibrationResult",
    "CalibrationModel",
    "CalibrationPlatform",
    "Calibrator",
    "PlattScalingCalibrator",
    "IsotonicCalibrator",
    "TemperatureScalingCalibrator",
    "CalibrationReport",
    "generate_calibration_report",
]
