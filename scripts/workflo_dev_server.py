"""Minimal Workflo control-plane server for smoke/CI environments.

Hosts ONLY the workflo router over real HTTP so the release gate can exercise
install -> connect -> sandbox -> execute -> report -> destroy without the full
Cortex stack (no database required). Not intended for production use.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.workflo import router as workflo_router  # noqa: E402


def create_workflo_app() -> FastAPI:
    app = FastAPI(title="Workflo Control Plane (standalone)", version="0.1.0")
    app.include_router(workflo_router, prefix="/api/v1")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_workflo_app()

if __name__ == "__main__":
    port = int(os.environ.get("WORKFLO_API_PORT", "8000"))
    root = os.environ.get("CORTEX_WORKFLO_ROOT")
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
