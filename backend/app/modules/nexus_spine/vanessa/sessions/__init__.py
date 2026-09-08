"""Nexus v0.7 — Production Vanessa Sessions.

Provides conversation state tied to operational context:
  - tenant / workspace / user / permissions
  - current_world_state
  - active_trace / selected_entity / selected_risk / selected_decision

This enables contextual conversations:
  "Why is it risky?" → Vanessa knows "it" is the selected supplier
  "What happens if we lose it?" → scenario
  "Compare that with the alternate supplier" → scenario comparison
  "What did we do last time?" → Decision Memory
"""

from app.modules.nexus_spine.vanessa.sessions.manager import (
    ConversationContext,
    VanessaSessionManager,
    get_vanessa_session_manager,
    reset_vanessa_session_manager,
)

__all__ = [
    "ConversationContext",
    "VanessaSessionManager",
    "get_vanessa_session_manager",
    "reset_vanessa_session_manager",
]
