"""Nexus Vanessa — Public interface for the investigation + orchestrator layer.

Vanessa runs as two synergistic engines:

1. VanessaOrchestrator (single-shot) — for straightforward queries, built to
   answer from a plan: intent -> plan -> tool execution.
2. VanessaInvestigator (multi-step) — for complex analysis, this can chain
   multiple tools into a sequence of grounded responses.

Both are importable from this module; `vanessa` defaults to the investigator.

Public API:
- classify_intent(): keyword-based intent detection
- VanessaOrchestrator / VanessaAnswer / VanessaQuery: single-step answers
- VanessaInvestigator / InvestigationResult / ResponseBlock: multi-step chains
"""

from app.modules.nexus_spine.vanessa.investigations.planner import (
    InvestigationResult,
    PlanStep,
    ResponseBlock,
    ResponseKind,
    VanessaInvestigator,
    get_vanessa_investigator,
    reset_vanessa_investigator,
    classify_intent as _classify_intent_impl,
)
from app.modules.nexus_spine.vanessa.orchestrator import (
    Intent,
    IntentClassification,
    VanessaAnswer,
    VanessaOrchestrator,
    VanessaQuery,
    classify_intent,
    get_vanessa,
    render_answer,
    reset_vanessa,
)
from app.modules.nexus_spine.vanessa.tools import (
    Tool,
    ToolCall,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    build_default_registry,
    reset_tool_registry,
)
from app.modules.nexus_spine.vanessa.builtin_tools import get_tool_registry

__all__ = [
    # Intent router
    "classify_intent",
    "ClassifyResult",
    # Models
    "Intent",
    "IntentClassification",
    # Single-step orchestrator
    "VanessaAnswer",
    "VanessaOrchestrator",
    "VanessaQuery",
    "render_answer",
    # Investigation + planner
    "VanessaInvestigator",
    "InvestigationResult",
    "PlanStep",
    "ResponseBlock",
    "ResponseKind",
    "get_vanessa_investigator",
    "reset_vanessa_investigator",
    #
    # Tool registry — user-facing
    "Tool",
    "ToolCall",
    "ToolPermission",
    "ToolRegistry",
    "ToolResult",
    "get_tool_registry",
    # Convenience for UI
    "get_vanessa",
    "reset_vanessa",
    "render_answer",
    "reset_vanessa",
    "build_default_registry",
    "reset_tool_registry",
    "reset_vanessa",
    # Tool types
    "Tool",
    "ToolCall",
    "ToolPermission",
    "ToolRegistry",
    "ToolResult",
]