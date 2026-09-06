"""
Node functions. Each takes the ConversationState and returns a dict
of the fields it changed — LangGraph merges that dict into state.

Pipeline per turn: extract_node -> retrieve_node -> evaluate_node ->
  (conditional) -> clarify_node | finalize_node

retrieve_node is a deliberate stub: the project's RAG/vector-store
phase (ChromaDB over scheme embeddings) hasn't been built yet, and
with only a handful of sample schemes, semantic retrieval doesn't add
much anyway. It returns every scheme as a "candidate" for now. Once
the vector store exists, only retrieve_node needs to change — nothing
downstream (evaluate_node, clarify_node) depends on how candidates
were chosen.
"""

from __future__ import annotations

from collections import Counter

from nlp_extraction.extractor import extract, merge_profile
from orchestration.questions import question_for_field
from orchestration.state import ConversationState
from rule_engine.engine import EligibilityStatus, evaluate_all
from explanation.generator import ExplanationGenerator, TemplateExplanationGenerator


def extract_node(state: ConversationState) -> dict:
    extraction = extract(state["user_message"])
    merged_profile = merge_profile(state["profile"], extraction.profile)
    return {
        "profile": merged_profile,
        "turn_count": state["turn_count"] + 1,
    }


def retrieve_node(state: ConversationState) -> dict:
    # STUB: replace with ChromaDB semantic search once the vector
    # store (project plan Phase 3) exists. See module docstring.
    return {"candidate_schemes": state["all_schemes"]}


def evaluate_node(state: ConversationState) -> dict:
    results = evaluate_all(state["candidate_schemes"], state["profile"])
    return {"results": results}


def route_after_evaluate(state: ConversationState) -> str:
    """Conditional edge: ask a clarifying question, or wrap up."""
    turns_left = state["turn_count"] < state["max_turns"]
    has_partial = any(
        r.status == EligibilityStatus.PARTIALLY_ELIGIBLE for r in state["results"]
    )
    if has_partial and turns_left:
        return "clarify"
    return "finalize"


def clarify_node(state: ConversationState) -> dict:
    """
    Pick the single most useful next question: the missing field that
    appears across the most PARTIALLY_ELIGIBLE candidate schemes,
    since resolving it moves the most schemes toward a final verdict
    in one question. Only pulls missing fields from PARTIALLY_ELIGIBLE
    results — a scheme that's already NOT_ELIGIBLE doesn't need more
    info, even if the engine recorded a MISSING_INFO condition on it
    too (see rule_engine/engine.py: FAIL always wins the overall
    status, but every condition is still evaluated and recorded).
    """
    partial_results = [
        r for r in state["results"] if r.status == EligibilityStatus.PARTIALLY_ELIGIBLE
    ]
    field_counts = Counter(
        field for r in partial_results for field in r.missing_fields
    )
    if not field_counts:
        # Shouldn't happen given route_after_evaluate's check, but fail
        # safe into finalize rather than asking an empty question.
        return {"awaiting_clarification": False, "clarification_question": None,
                "clarification_field": None}

    field_name, _ = field_counts.most_common(1)[0]
    return {
        "awaiting_clarification": True,
        "clarification_question": question_for_field(field_name),
        "clarification_field": field_name,
        "done": False,
    }


def finalize_node(
    state: ConversationState,
    explanation_generator: ExplanationGenerator = None,
) -> dict:
    generator = explanation_generator or TemplateExplanationGenerator()
    return {
        "awaiting_clarification": False,
        "clarification_question": None,
        "clarification_field": None,
        "done": True,
        "explanations": generator.generate_all(state["results"]),
    }
