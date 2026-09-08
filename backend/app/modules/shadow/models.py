"""Shadow Inference Module — Run models in shadow mode without affecting production."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ShadowInferenceRequest(BaseModel):
    """Request to run shadow inference."""

    model_id: UUID
    model_version: str
    input_data: dict
    request_id: str | None = None
    timeout_seconds: float = 30.0


class ShadowInferenceResult(BaseModel):
    """Result of a shadow inference."""

    inference_id: UUID = Field(default_factory=uuid4)
    model_id: UUID
    model_version: str
    request_id: str | None
    input_data: dict
    prediction: dict
    latency_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


class ShadowComparison(BaseModel):
    """Comparison between production and shadow model outputs."""

    comparison_id: UUID = Field(default_factory=uuid4)
    request_id: str
    production_model_id: UUID
    production_version: str
    shadow_model_id: UUID
    shadow_version: str
    input_data: dict
    production_output: dict
    shadow_output: dict
    agreement: bool
    disagreement_details: dict = {}
    latency_production_ms: float
    latency_shadow_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ShadowInferenceEngine:
    """Runs shadow inference alongside production model."""

    def __init__(self):
        self.shadow_models: dict[str, ShadowModelWrapper] = {}
        self.comparisons: list[ShadowComparison] = []
        self.inference_history: list[ShadowInferenceResult] = []

    def register_shadow_model(
        self, model_id: UUID, version: str, model_wrapper: ShadowModelWrapper
    ) -> None:
        """Register a shadow model."""
        key = f"{model_id}_{version}"
        self.shadow_models[key] = model_wrapper

    async def run_shadow_inference(self, request: ShadowInferenceRequest) -> ShadowInferenceResult:
        """Run inference on a shadow model."""
        key = f"{request.model_id}_{request.model_version}"
        wrapper = self.shadow_models.get(key)

        if not wrapper:
            return ShadowInferenceResult(
                model_id=request.model_id,
                model_version=request.model_version,
                request_id=request.request_id,
                input_data=request.input_data,
                prediction={},
                latency_ms=0.0,
                error=f"Shadow model {key} not registered",
            )

        start = time.time()
        try:
            prediction = await asyncio.wait_for(
                wrapper.predict(request.input_data),
                timeout=request.timeout_seconds,
            )
            latency = (time.time() - start) * 1000

            result = ShadowInferenceResult(
                model_id=request.model_id,
                model_version=request.model_version,
                request_id=request.request_id,
                input_data=request.input_data,
                prediction=prediction,
                latency_ms=latency,
            )
        except TimeoutError:
            latency = (time.time() - start) * 1000
            result = ShadowInferenceResult(
                model_id=request.model_id,
                model_version=request.model_version,
                request_id=request.request_id,
                input_data=request.input_data,
                prediction={},
                latency_ms=latency,
                error=f"Timeout after {request.timeout_seconds}s",
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            result = ShadowInferenceResult(
                model_id=request.model_id,
                model_version=request.model_version,
                request_id=request.request_id,
                input_data=request.input_data,
                prediction={},
                latency_ms=latency,
                error=str(e),
            )

        self.inference_history.append(result)
        return result

    async def run_shadow_comparison(
        self,
        production_model_id: UUID,
        production_version: str,
        shadow_model_id: UUID,
        shadow_version: str,
        input_data: dict,
        request_id: str,
    ) -> ShadowComparison:
        """Run both production and shadow models and compare outputs."""
        # Run production model (would call actual production endpoint)
        production_start = time.time()
        try:
            # This would call the actual production model
            production_output = {"placeholder": "production_output"}
        except Exception as e:
            production_output = {"error": str(e)}
        prod_latency = (time.time() - production_start) * 1000

        # Run shadow model
        shadow_key = f"{shadow_model_id}_{shadow_version}"
        shadow_wrapper = self.shadow_models.get(shadow_key)
        shadow_start = time.time()

        try:
            if shadow_wrapper:
                shadow_output = await asyncio.wait_for(
                    shadow_wrapper.predict(input_data),
                    timeout=30.0,
                )
            else:
                shadow_output = {"error": "Shadow model not registered"}
        except Exception as e:
            shadow_output = {"error": str(e)}
        shadow_latency = (time.time() - shadow_start) * 1000

        # Compare outputs
        agreement, details = self._compare_outputs(production_output, shadow_output)

        comparison = ShadowComparison(
            request_id="",
            production_model_id=production_model_id,
            production_version=production_version,
            shadow_model_id=shadow_model_id,
            shadow_version=shadow_version,
            input_data=input_data,
            production_output=production_output,
            shadow_output=shadow_output,
            agreement=agreement,
            disagreement_details=details,
            latency_production_ms=prod_latency,
            latency_shadow_ms=shadow_latency,
        )

        return comparison

    def _compare_outputs(self, prod: dict, shadow: dict) -> tuple[bool, dict]:
        """Compare two model outputs."""
        if "error" in prod or "error" in shadow:
            return False, {"error": "One or both models errored"}

        details = {}
        agreement = True

        # Compare keys
        prod_keys = set(prod.keys())
        shadow_keys = set(shadow.keys())
        missing_in_shadow = prod_keys - shadow_keys
        extra_in_shadow = shadow_keys - prod_keys

        if missing_in_shadow:
            agreement = False
            details["missing_in_shadow"] = list(missing_in_shadow)
        if extra_in_shadow:
            agreement = False
            details["extra_in_shadow"] = list(extra_in_shadow)

        # Compare common keys
        common_keys = prod.keys() & shadow_keys
        for key in common_keys:
            prod_val = prod[key]
            shadow_val = shadow[key]

            if isinstance(prod_val, (int, float)) and isinstance(shadow_val, (int, float)):
                rel_diff = abs(prod_val - shadow_val) / max(abs(prod_val), 1e-9)
                if rel_diff > 0.05:  # 5% tolerance
                    agreement = False
                    details[f"{key}_diff"] = rel_diff
            elif prod_val != shadow_val:
                agreement = False
                details[f"{key}_mismatch"] = {"prod": prod_val, "shadow": shadow_val}

        return agreement, details


class ShadowModelWrapper:
    """Wrapper for a shadow model."""

    def __init__(self, model_id: UUID, version: str, predict_fn):
        self.model_id = model_id
        self.version = version
        self.predict_fn = predict_fn
        self.call_count = 0
        self.total_latency = 0.0
        self.error_count = 0

    async def predict(self, input_data: dict) -> dict:
        """Run prediction."""
        start = time.time()
        try:
            if asyncio.iscoroutinefunction(self.predict_fn):
                result = await self.predict_fn(input_data)
            else:
                result = self.predict_fn(input_data)
            self.call_count += 1
            self.total_latency += time.time() - start
            return result
        except Exception:
            self.error_count += 1
            raise

    def get_stats(self) -> dict:
        return {
            "model_id": str(self.model_id),
            "version": self.version,
            "call_count": self.call_count,
            "avg_latency_ms": (self.total_latency / self.call_count * 1000)
            if self.call_count > 0
            else 0,
            "error_count": self.error_count,
            "error_rate": self.error_count / self.call_count if self.call_count > 0 else 0,
        }


class ShadowDeploymentManager:
    """Manages shadow deployments."""

    def __init__(self):
        self.engine = ShadowInferenceEngine()
        self.deployments: dict[str, dict] = {}

    def create_shadow_deployment(
        self,
        name: str,
        production_model_id: UUID,
        production_version: str,
        shadow_model_id: UUID,
        shadow_version: str,
        predict_fn,
        traffic_percentage: float = 0.0,
    ) -> str:
        """Create a shadow deployment."""
        deployment_id = f"shadow_{uuid4().hex[:8]}"
        wrapper = ShadowModelWrapper(shadow_model_id, str(shadow_version), predict_fn)

        self.engine.register_shadow_model(shadow_model_id, str(shadow_version), wrapper)

        self.deployments[deployment_id] = {
            "name": name,
            "production_model_id": production_model_id,
            "production_version": production_version,
            "shadow_model_id": shadow_model_id,
            "shadow_version": shadow_version,
            "traffic_percentage": traffic_percentage,
            "created_at": datetime.now(UTC),
            "status": "active",
            "stats": {"total_requests": 0, "comparisons": 0, "agreements": 0},
        }

        return deployment_id

    async def process_request(
        self,
        deployment_id: str,
        input_data: dict,
        request_id: str,
    ) -> ShadowComparison | None:
        """Process a request through both production and shadow."""
        deployment = self.deployments.get(deployment_id)
        if not deployment or deployment["status"] != "active":
            return None

        # In real implementation, would call actual production endpoint
        # For now, return a mock comparison
        return ShadowComparison(
            request_id="",
            production_model_id=deployment["production_model_id"],
            production_version=deployment["production_version"],
            shadow_model_id=deployment["shadow_model_id"],
            shadow_version=deployment["shadow_version"],
            input_data=input_data,
            production_output={"mock": "production"},
            shadow_output={"mock": "shadow"},
            agreement=True,
            disagreement_details={},
            latency_production_ms=10.0,
            latency_shadow_ms=15.0,
        )

    def get_deployment_stats(self, deployment_id: str) -> dict | None:
        deployment = self.deployments.get(deployment_id)
        if not deployment:
            return None
        return deployment["stats"]


__all__ = [
    "ShadowInferenceRequest",
    "ShadowInferenceResult",
    "ShadowComparison",
    "ShadowInferenceEngine",
    "ShadowModelWrapper",
    "ShadowDeploymentManager",
]
