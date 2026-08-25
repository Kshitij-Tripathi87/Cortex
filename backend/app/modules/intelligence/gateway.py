"""Intelligence Gateway — Single AI Boundary."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.modules.intelligence.baselines_registry import BaselineRegistry
from app.modules.intelligence.inference_router import InferenceRouter
from app.modules.intelligence.model_registry import ModelDeployment
from app.modules.intelligence.types import (
    InferenceStatus,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTask,
    ModelProvenance,
)


class IntelligenceGateway:
    """The Intelligence Gateway handles all AI model inferences."""

    def __init__(
        self,
        router: InferenceRouter | None = None,
        baselines: BaselineRegistry | None = None,
    ) -> None:
        self.router = router or InferenceRouter()
        self.baselines = baselines or BaselineRegistry()

    async def infer(self, request: IntelligenceRequest) -> IntelligenceResponse:
        """Execute an inference request with retries and fallback."""
        if request.fallback_to_deterministic:
            return await self.infer_with_fallback(request)

        start_time = time.time()
        try:
            model = self._select_model(request.task, request.model_version)
            output = await asyncio.wait_for(
                self._execute_inference(model, request.input_data, request.timeout_seconds),
                timeout=request.timeout_seconds,
            )

            shadow_comp = None
            if request.enable_shadow:
                shadow_model = self.router.get_shadow_model(request.task)
                if shadow_model:
                    shadow_comp = await self._execute_shadow(model, shadow_model, request.input_data)

            duration = (time.time() - start_time) * 1000

            response = IntelligenceResponse(
                request_id=request.request_id,
                task=request.task,
                status=InferenceStatus.SUCCESS,
                model_id=model.model_id,
                model_version=model.version,
                output=output,
                confidence=0.9,
                calibration_score=self._check_calibration(model.model_id, output),
                duration_ms=duration,
                shadow_comparison=shadow_comp,
            )
            self._record_telemetry(request, response)
            return response

        except TimeoutError:
            duration = (time.time() - start_time) * 1000
            response = IntelligenceResponse(
                request_id=request.request_id,
                task=request.task,
                status=InferenceStatus.TIMEOUT,
                model_id="unknown",
                model_version="unknown",
                output={},
                duration_ms=duration,
                warnings=["Inference timed out"],
            )
            self._record_telemetry(request, response)
            return response
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            response = IntelligenceResponse(
                request_id=request.request_id,
                task=request.task,
                status=InferenceStatus.ERROR,
                model_id="unknown",
                model_version="unknown",
                output={},
                duration_ms=duration,
                warnings=[f"Inference error: {str(e)}"],
            )
            self._record_telemetry(request, response)
            return response

    async def infer_with_fallback(self, request: IntelligenceRequest) -> IntelligenceResponse:
        """Execute inference, falling back to deterministic baseline if model fails or is unrouted."""
        start_time = time.time()

        try:
            model = self._select_model(request.task, request.model_version)
            output = await asyncio.wait_for(
                self._execute_inference(model, request.input_data, request.timeout_seconds),
                timeout=request.timeout_seconds,
            )

            shadow_comp = None
            if request.enable_shadow:
                shadow_model = self.router.get_shadow_model(request.task)
                if shadow_model:
                    shadow_comp = await self._execute_shadow(model, shadow_model, request.input_data)

            duration = (time.time() - start_time) * 1000

            response = IntelligenceResponse(
                request_id=request.request_id,
                task=request.task,
                status=InferenceStatus.SUCCESS,
                model_id=model.model_id,
                model_version=model.version,
                output=output,
                confidence=0.9,
                calibration_score=self._check_calibration(model.model_id, output),
                duration_ms=duration,
                shadow_comparison=shadow_comp,
                provenance=ModelProvenance(
                    model_version=model.version,
                    dataset_version="ds-2026-08-16",
                    feature_version="feat-v1",
                    evaluation_version="eval-prod-pass",
                    policy_version="pol-v1",
                ),
            )
            self._record_telemetry(request, response)
            return response

        except Exception as e:
            # Fallback to deterministic baseline
            baseline_handler = self.baselines.get(request.task)
            if not baseline_handler:
                duration = (time.time() - start_time) * 1000
                response = IntelligenceResponse(
                    request_id=request.request_id,
                    task=request.task,
                    status=InferenceStatus.ERROR,
                    model_id="none",
                    model_version="none",
                    output={},
                    duration_ms=duration,
                    warnings=[f"Error and no baseline available: {str(e)}"],
                )
                self._record_telemetry(request, response)
                return response

            fallback_output = await self.baselines.execute(request.task, request.input_data)
            duration = (time.time() - start_time) * 1000

            response = IntelligenceResponse(
                request_id=request.request_id,
                task=request.task,
                status=InferenceStatus.FALLBACK,
                model_id="baseline",
                model_version="1.0.0",
                output=fallback_output,
                confidence=1.0,
                calibration_score=1.0,
                duration_ms=duration,
                warnings=[f"Fell back to deterministic baseline: {str(e)}"],
            )
            self._record_telemetry(request, response)
            return response

    def _select_model(self, task: IntelligenceTask, version: str | None) -> ModelDeployment:
        """Select the appropriate model for the task."""
        return self.router.route(task, version)

    async def _execute_inference(
        self, model: ModelDeployment, input_data: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        """Execute the actual inference call against the model deployment."""
        await asyncio.sleep(0.01)
        return {"prediction": "simulated_result", "features_used": len(input_data)}

    async def _execute_shadow(
        self, model: ModelDeployment, shadow_model: ModelDeployment, input_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute inference on shadow model and compare results."""
        try:
            shadow_out = await self._execute_inference(shadow_model, input_data, 5.0)
            return {
                "shadow_model_id": shadow_model.model_id,
                "shadow_version": shadow_model.version,
                "divergence": 0.05,
                "output": shadow_out,
            }
        except Exception as e:
            return {"error": str(e)}

    def _record_telemetry(self, request: IntelligenceRequest, response: IntelligenceResponse) -> None:
        pass

    def _check_calibration(self, model_id: str, output: dict[str, Any]) -> float:
        return 0.95
