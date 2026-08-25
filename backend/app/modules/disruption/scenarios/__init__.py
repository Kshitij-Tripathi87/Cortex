"""Backtest scenario library — deterministic, traceable disruption events with known outcomes.

Each module defines one scenario type. Only supplier_delay is complete for MVP;
factory_fire, port_closure, and inventory_shortage are documented only.

Every scenario module exposes:

    build() -> tuple[SupplyChainSnapshot, DisruptionScenario, BacktestLabels]
        Construct the canonical (snapshot, scenario, ground_truth) triple for that
        scenario. Calling ``build()`` with the same arguments always returns the
        same result (ADR-0003).
"""

from __future__ import annotations

from app.modules.disruption.scenarios.supplier_delay import build as build_supplier_delay

__all__ = ["build_supplier_delay"]
