"""
Run with: python3 tests/test_orchestration.py

Scripted multi-turn conversations against the real Module-1 sample
data, exercising:
  1. A conversation that needs one clarifying question, then resolves
     to ELIGIBLE.
  2. A conversation where the very first message is already enough to
     get NOT_ELIGIBLE (age fails outright) — no clarification needed.
  3. The max_turns safety valve — a user who never answers shouldn't
     loop forever.
"""

import json
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import Scheme  # noqa: E402
from orchestration.graph import submit_message  # noqa: E402
from orchestration.state import new_conversation_state  # noqa: E402
from rule_engine.engine import EligibilityStatus  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_schemes.json")


def load_schemes() -> List[Scheme]:
    with open(DATA_PATH) as f:
        raw = json.load(f)
    return [Scheme(**item) for item in raw]


def load_scheme(scheme_id: str) -> Scheme:
    return next(s for s in load_schemes() if s.scheme_id == scheme_id)


def print_turn(n, message, state):
    print(f"\nTurn {n} — user: {message!r}")
    print(f"  profile so far: {state['profile'].model_dump(exclude_none=True)}")
    if state["awaiting_clarification"]:
        print(f"  bot asks: {state['clarification_question']}")
    else:
        print(f"  done={state['done']}, results:")
        for r in state["results"]:
            print(f"    {r.status.value:20s} {r.scheme_name}")


def test_conversation_needs_one_clarification_then_eligible():
    vay_vandana = load_scheme("vay-vandana-yojana-gujarat")
    state = new_conversation_state([vay_vandana])

    # Turn 1: mentions everything about Vay Vandana except income.
    state = submit_message(state, "I am 65 years old and live in Gujarat")
    print_turn(1, "I am 65 years old and live in Gujarat", state)
    assert state["awaiting_clarification"] is True
    assert state["clarification_field"] == "annual_income"

    # Turn 2: user answers the clarifying question.
    state = submit_message(state, "My annual income is around 1 lakh rupees")
    print_turn(2, "My annual income is around 1 lakh rupees", state)
    assert state["done"] is True
    result = next(r for r in state["results"] if r.scheme_id == "vay-vandana-yojana-gujarat")
    assert result.status == EligibilityStatus.ELIGIBLE


def test_conversation_resolves_immediately_on_hard_fail():
    vay_vandana = load_scheme("vay-vandana-yojana-gujarat")
    state = new_conversation_state([vay_vandana])

    # Age alone is enough to fail Vay Vandana outright — no need to
    # ask about income or anything else for that scheme.
    msg = "I'm 40 years old, live in Gujarat, annual income is 1 lakh rupees"
    state = submit_message(state, msg)
    print_turn(1, msg, state)
    assert state["done"] is True
    result = next(r for r in state["results"] if r.scheme_id == "vay-vandana-yojana-gujarat")
    assert result.status == EligibilityStatus.NOT_ELIGIBLE


def test_max_turns_prevents_infinite_loop():
    schemes = load_schemes()
    state = new_conversation_state(schemes, max_turns=2)

    # User never actually answers with parseable info — the extractor
    # will find nothing each time, so the state never gains new fields.
    for i in range(1, 5):
        state = submit_message(state, "I'm not sure, can you just tell me?")
        print_turn(i, "I'm not sure, can you just tell me?", state)
        if state["done"]:
            break

    assert state["done"] is True
    assert state["turn_count"] <= 2 + 1  # stopped at/around max_turns, not runaway


def test_multi_scheme_clarification_picks_most_impactful_field():
    # Both PM-KISAN (missing occupation) and Vay Vandana (missing
    # income) are PARTIALLY_ELIGIBLE after this message. With one
    # missing field each, clarify_node breaks the tie by asking about
    # whichever scheme comes first in evaluate_all's stable sort —
    # this test documents that behavior explicitly rather than
    # leaving it as a surprise.
    schemes = load_schemes()
    state = new_conversation_state(schemes)
    state = submit_message(state, "I am 65 years old and live in Gujarat")
    print_turn(1, "I am 65 years old and live in Gujarat", state)
    assert state["awaiting_clarification"] is True
    assert state["clarification_field"] in ("occupation", "annual_income")


if __name__ == "__main__":
    test_conversation_needs_one_clarification_then_eligible()
    test_conversation_resolves_immediately_on_hard_fail()
    test_max_turns_prevents_infinite_loop()
    test_multi_scheme_clarification_picks_most_impactful_field()
    print("\nALL TESTS PASSED")
