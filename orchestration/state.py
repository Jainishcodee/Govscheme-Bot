"""
The state object LangGraph threads through every node. One node's
output becomes the next node's input; the whole conversation's
progress lives here — nothing is hidden in closures or globals.

Plain TypedDict rather than a Pydantic model: no field needs a merge
reducer (this graph is a single linear chain per turn, not a
fan-out/fan-in graph), so a TypedDict keeps things simple and is what
most LangGraph examples use.
"""

from __future__ import annotations

from typing import Dict, List, Optional, TypedDict

from schema import Scheme
from rule_engine.engine import EligibilityResult
from rule_engine.user_profile import UserProfile


class ConversationState(TypedDict):
    # --- input for this turn ---
    user_message: str

    # --- accumulated across turns ---
    profile: UserProfile
    turn_count: int
    max_turns: int

    # --- populated by nodes each turn ---
    all_schemes: List[Scheme]          # loaded once at conversation start
    candidate_schemes: List[Scheme]     # after retrieve_node
    results: List[EligibilityResult]    # after evaluate_node
    explanations: Dict[str, str]        # after finalize_node

    # --- turn outcome ---
    awaiting_clarification: bool
    clarification_question: Optional[str]
    clarification_field: Optional[str]  # which condition field the question targets
    done: bool                          # True once ready for Module 6 (explanation) / final display


def new_conversation_state(all_schemes: List[Scheme], max_turns: int = 5) -> ConversationState:
    return ConversationState(
        user_message="",
        profile=UserProfile(),
        turn_count=0,
        max_turns=max_turns,
        all_schemes=all_schemes,
        candidate_schemes=[],
        results=[],
        explanations={},
        awaiting_clarification=False,
        clarification_question=None,
        clarification_field=None,
        done=False,
    )
