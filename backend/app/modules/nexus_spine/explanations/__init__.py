"""Nexus v0.7 — Explanation Engine ("Why?" engine).

Every serious Nexus output should answer:
  WHAT?
  WHY?
  IMPACT?
  CONFIDENCE?
  EVIDENCE?
  WHAT NEXT?

This is a reusable explanation model throughout the UI and Vanessa.
"""

from app.modules.nexus_spine.explanations.engine import (
    Explanation,
    ExplanationBlock,
    ExplanationEngine,
    ResponseBlockType,
    get_explanation_engine,
    reset_explanation_engine,
)

__all__ = [
    "Explanation",
    "ExplanationBlock",
    "ExplanationEngine",
    "ResponseBlockType",
    "get_explanation_engine",
    "reset_explanation_engine",
]
