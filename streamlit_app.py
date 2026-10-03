"""
Streamlit demo — combines every module built so far into one working
chat app:

  Module 1  schema.py, scrapers/       -> data/sample_schemes.json is loaded as the scheme corpus
  Module 3  rule_engine/                -> deterministic eligibility decisions
  Module 4  nlp_extraction/              -> free text -> UserProfile
  RAG       retrieval/                    -> ChromaDB + TF-IDF semantic search over the scheme corpus
  Module 5  orchestration/                -> LangGraph turn-by-turn state machine
  Module 6  explanation/                   -> decision -> natural language

Run with:
    streamlit run streamlit_app.py

Works with ZERO configuration (uses TemplateExplanationGenerator and
an offline TF-IDF retriever — see retrieval/embeddings.py for why no
model download is required). If you set an ANTHROPIC_API_KEY
environment variable before running, it automatically upgrades to
LLM-generated explanations, falling back to templates silently if any
API call fails — see the sidebar for which mode is active.
"""

from __future__ import annotations

import json
import os

import streamlit as st

from schema import Scheme
from explanation.generator import LLMExplanationGenerator, TemplateExplanationGenerator, anthropic_llm_call
from orchestration.graph import build_graph, submit_message
from orchestration.state import new_conversation_state
from retrieval.retriever import SchemeRetriever
from rule_engine.engine import EligibilityStatus

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "sample_schemes.json")
SCRAPED_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "myscheme_schemes.json")

STATUS_DISPLAY = {
    EligibilityStatus.ELIGIBLE: ("✅", "Eligible"),
    EligibilityStatus.NOT_ELIGIBLE: ("❌", "Not eligible"),
    EligibilityStatus.PARTIALLY_ELIGIBLE: ("🟡", "Need more info"),
    EligibilityStatus.NEEDS_MANUAL_REVIEW: ("🔎", "Needs manual review"),
}


@st.cache_resource
def load_schemes() -> list[Scheme]:
    paths = [DATA_PATH]
    if os.path.exists(SCRAPED_DATA_PATH):
        paths.append(SCRAPED_DATA_PATH)

    schemes_by_source_url = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for item in json.load(f):
                scheme = Scheme(**item)
                schemes_by_source_url[str(scheme.source_url)] = scheme
    return list(schemes_by_source_url.values())


@st.cache_resource
def get_retriever() -> SchemeRetriever:
    """
    Builds the ChromaDB-backed index once per server process. With
    only 3 schemes in this demo corpus, top_k=5 never actually
    excludes anything — retrieval only starts genuinely narrowing
    candidates once Module 1's dataset grows past a handful of
    schemes. See retrieval/README notes and tests/test_retrieval.py
    for a larger synthetic corpus that demonstrates real filtering.
    """
    return SchemeRetriever.from_schemes(load_schemes(), default_top_k=5)


@st.cache_resource
def get_graph_and_mode():
    """
    Builds the graph once per server process. Upgrades to LLM
    explanations automatically if ANTHROPIC_API_KEY is set and the
    'anthropic' package is installed; falls back to templates
    otherwise (or silently per-call if an API request fails — see
    LLMExplanationGenerator's own fallback in explanation/generator.py).
    """
    retriever = get_retriever()
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            generator = LLMExplanationGenerator(anthropic_llm_call())
            return build_graph(generator, retriever=retriever), "llm"
        except Exception:
            pass
    return build_graph(TemplateExplanationGenerator(), retriever=retriever), "template"


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
        all_schemes = load_schemes()
        candidate_ids = {
            s.scheme_id for s in st.session_state.conversation_state["candidate_schemes"]
        }
        turn_count = st.session_state.conversation_state["turn_count"]
        for s in all_schemes:
            if turn_count > 0 and s.scheme_id not in candidate_ids:
                st.caption(f"·  ~~{s.name}~~  _(not retrieved this turn)_")
            else:
                st.caption(f"•  {s.name}")
        if turn_count > 0:
            st.caption(
                f"RAG retrieved {len(candidate_ids)} of {len(all_schemes)} schemes as "
                f"candidates this turn (TF-IDF + ChromaDB, ranked against everything "
                f"you've said so far). With only {len(all_schemes)} schemes in this demo "
                f"corpus, retrieval rarely excludes anything — see tests/test_retrieval.py "
                f"for a larger corpus where it actually filters."
            )

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
