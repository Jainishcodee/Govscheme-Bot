"""
Compiles the orchestration graph:

    START -> extract -> retrieve -> evaluate -> (route) -> clarify -> END
                                                          -> finalize -> explain -> END

One graph.invoke() call = one user turn. The "loop" the project plan
describes (clarify_node conditional loop) happens *across* invoke()
calls, driven by the application: ask the clarifying question, wait
for the user's next message, invoke() again with the updated state.
This mirrors how a real chat UI works (each user message is a
separate request) and avoids needing LangGraph's interrupt/checkpoint
machinery for what is, for this project's scope, a straightforward
multi-turn form-filling conversation.

`explain_node` only runs once the turn resolves to `finalize` — no
point generating explanation text for results that might still change
next turn.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from explanation.generator import ExplanationGenerator
from orchestration.nodes import (
    clarify_node,
    evaluate_node,
    extract_node,
    finalize_node,
    make_explain_node,
    retrieve_node,
    route_after_evaluate,
)
from orchestration.state import ConversationState


def build_graph(explanation_generator: ExplanationGenerator | None = None):
    graph = StateGraph(ConversationState)

    graph.add_node("extract", extract_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("explain", make_explain_node(explanation_generator))

    graph.set_entry_point("extract")
    graph.add_edge("extract", "retrieve")
    graph.add_edge("retrieve", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"clarify": "clarify", "finalize": "finalize"},
    )
    graph.add_edge("clarify", END)
    graph.add_edge("finalize", "explain")
    graph.add_edge("explain", END)

    return graph.compile()


# Built once with default (template) explanations, reused across
# turns/tests. Call build_graph(explanation_generator=...) directly if
# you want an LLM-backed graph instead — see streamlit_app.py for how
# the demo picks between them based on whether an API key is set.
COMPILED_GRAPH = build_graph()


def submit_message(state: ConversationState, message: str, graph=None) -> ConversationState:
    """Run one turn: feed in the user's message, get back updated state."""
    state = dict(state)  # shallow copy — don't mutate the caller's state in place
    state["user_message"] = message
    return (graph or COMPILED_GRAPH).invoke(state)
