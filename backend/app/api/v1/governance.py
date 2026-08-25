"""Governance API v1 — Closed-Loop Continuous Learning & Governance Endpoints.

Program O (Closed-Loop Continuous Learning & Operational Governance):
- GET /governance/flywheel — Retrieve closed-loop feedback report and model calibration metrics
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.execution import _execution_service
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.governance.flywheel_service import ClosedLoopFlywheelService

router = APIRouter()
logger = logging.getLogger(__name__)

_flywheel_service = ClosedLoopFlywheelService()


@router.get("/flywheel")
async def get_flywheel_report(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve continuous learning flywheel metrics and subsystem calibrations."""
    require_workspace_access(workspace_id, auth)

    report = _flywheel_service.generate_governance_report(
        workspace_id=workspace_id,
        memory_store=_execution_service.memory_store,
    )
    return report.to_dict()
