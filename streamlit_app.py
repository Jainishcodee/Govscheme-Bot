"""
Streamlit demo — combines every module built so far into one working
chat app:

  Module 1  schema.py, scrapers/       -> data/sample_schemes.json is loaded as the scheme corpus
  Module 3  rule_engine/                -> deterministic eligibility decisions
  Module 4  nlp_extraction/              -> free text -> UserProfile
  Module 5  orchestration/                -> LangGraph turn-by-turn state machine
  Module 6  explanation/                   -> decision -> natural language

Run with:
    streamlit run streamlit_app.py

Works with ZERO configuration (uses TemplateExplanationGenerator).
If you set an ANTHROPIC_API_KEY environment variable before running,
it automatically upgrades to LLM-generated explanations, falling back
to templates silently if any API call fails — see the sidebar for
which mode is active.
"""

from __future__ import annotations

import json
import os

import streamlit as st

from schema import Scheme
from explanation.generator import LLMExplanationGenerator, TemplateExplanationGenerator, anthropic_llm_call
from orchestration.graph import build_graph, submit_message
from orchestration.state import new_conversation_state
from rule_engine.engine import EligibilityStatus

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "sample_schemes.json")

STATUS_DISPLAY = {
    EligibilityStatus.ELIGIBLE: ("✅", "Eligible"),
    EligibilityStatus.NOT_ELIGIBLE: ("❌", "Not eligible"),
    EligibilityStatus.PARTIALLY_ELIGIBLE: ("🟡", "Need more info"),
    EligibilityStatus.NEEDS_MANUAL_REVIEW: ("🔎", "Needs manual review"),
}


@st.cache_resource
def load_schemes() -> list[Scheme]:
    with open(DATA_PATH) as f:
        raw = json.load(f)
    return [Scheme(**item) for item in raw]


@st.cache_resource
def get_graph_and_mode():
    """
    Builds the graph once per server process. Upgrades to LLM
    explanations automatically if ANTHROPIC_API_KEY is set and the
    'anthropic' package is installed; falls back to templates
    otherwise (or silently per-call if an API request fails — see
    LLMExplanationGenerator's own fallback in explanation/generator.py).
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            generator = LLMExplanationGenerator(anthropic_llm_call())
            return build_graph(generator), "llm"
        except Exception:
            pass
    return build_graph(TemplateExplanationGenerator()), "template"


def init_session_state():
    if "conversation_state" not in st.session_state:
        schemes = load_schemes()
        st.session_state.conversation_state = new_conversation_state(schemes, max_turns=6)
        st.session_state.chat_history = [
            ("assistant", "Hi! Tell me a bit about yourself — age, income, "
                          "occupation, state — and I'll check which schemes you may qualify for.")
        ]


def reset_conversation():
    for key in ("conversation_state", "chat_history"):
        st.session_state.pop(key, None)
    init_session_state()


def render_results(state):
    for result in state["results"]:
        icon, label = STATUS_DISPLAY[result.status]
        with st.expander(f"{icon} **{result.scheme_name}** — {label}", expanded=True):
            explanation = state["explanations"].get(result.scheme_id, "")
            st.write(explanation)
            with st.popover("Show condition-by-condition detail"):
                for c in result.conditions:
                    c_icon = {
                        "pass": "✅", "fail": "❌",
                        "missing_info": "❓", "needs_review": "🔎",
                    }.get(c.status.value, "•")
                    st.markdown(f"{c_icon} `{c.field}` — {c.message}")


def main():
    st.set_page_config(page_title="Govt. Scheme Eligibility Chatbot", page_icon="🏛️")
    st.title("🏛️ Government Scheme Eligibility Chatbot")
    st.caption(
        "Hybrid architecture: rule engine decides eligibility deterministically; "
        "an LLM only ever rephrases an already-made decision, never invents one."
    )

    graph, mode = get_graph_and_mode()
    init_session_state()

    with st.sidebar:
        st.subheader("Session info")
        st.write(f"Explanation mode: **{'LLM (Anthropic)' if mode == 'llm' else 'Template (offline)'}**")
        profile = st.session_state.conversation_state["profile"]
        known = profile.model_dump(exclude_none=True)
        st.write("**What we know about you:**")
        st.json(known if known else {"(nothing yet)": ""})
        st.write(f"Turn {st.session_state.conversation_state['turn_count']} "
                 f"/ {st.session_state.conversation_state['max_turns']}")
        if st.button("Start over"):
            reset_conversation()
            st.rerun()

        st.divider()
        st.subheader("Schemes in this demo")
        for s in load_schemes():
            st.caption(f"• {s.name}")

    for role, content in st.session_state.chat_history:
        with st.chat_message(role):
            st.write(content)

    user_input = st.chat_input("Tell me about yourself...")
    if user_input:
        st.session_state.chat_history.append(("user", user_input))
        state = submit_message(st.session_state.conversation_state, user_input, graph=graph)
        st.session_state.conversation_state = state

        if state["awaiting_clarification"]:
            st.session_state.chat_history.append(("assistant", state["clarification_question"]))
        else:
            st.session_state.chat_history.append(
                ("assistant", "Here's what I found — see the summary below.")
            )
        # Rerun so the sidebar (profile, turn count) and the results
        # section below reflect this turn's update immediately, rather
        # than lagging one interaction behind — Streamlit doesn't
        # re-render already-executed widgets within the same run.
        st.rerun()

    # Re-render final results below the chat on every rerun, once done,
    # so they don't disappear after the message that produced them.
    if st.session_state.conversation_state["done"] and st.session_state.conversation_state["results"]:
        st.divider()
        st.subheader("Latest eligibility summary")
        render_results(st.session_state.conversation_state)


if __name__ == "__main__":
    main()
