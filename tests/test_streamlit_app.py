"""
Run with: python3 tests/test_streamlit_app.py

Uses Streamlit's own `AppTest` framework to drive the real app
(streamlit_app.py) in-process: simulates actual chat_input submissions
and button clicks, and asserts on what would actually render. No
browser, no `streamlit run` server needed — this genuinely exercises
the UI code, not just the modules it calls.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = os.path.join(os.path.dirname(__file__), "..", "streamlit_app.py")


def fresh_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception, f"App raised on initial load: {at.exception}"
    return at


def test_app_boots_with_greeting():
    at = fresh_app()
    assert len(at.chat_message) == 1
    assert "Hi!" in at.chat_message[0].markdown[0].value


def test_multi_turn_conversation_reaches_eligible_verdict():
    at = fresh_app()
    at.chat_input[0].set_value("I am 65 years old and live in Gujarat").run()
    assert not at.exception
    assert "occupation" in at.chat_message[-1].markdown[0].value.lower()

    at.chat_input[0].set_value("I work as a farmer").run()
    assert not at.exception
    assert "income" in at.chat_message[-1].markdown[0].value.lower()

    at.chat_input[0].set_value("My annual income is around 1 lakh rupees").run()
    assert not at.exception

    labels = [e.label for e in at.expander]
    assert any("Vay Vandana" in l and "Eligible" in l for l in labels)
    assert any("PM-KISAN" in l and "manual review" in l for l in labels)


def test_sidebar_profile_updates_immediately_not_lagged():
    at = fresh_app()
    at.chat_input[0].set_value(
        "I'm 40 years old, live in Gujarat, work as a teacher, annual income is 1 lakh rupees"
    ).run()
    assert not at.exception
    profile_json = at.sidebar.json[0].value
    assert '"age": 40' in profile_json
    assert '"occupation": "teacher"' in profile_json
    # This is the regression check for the lag bug found during manual
    # testing: the sidebar must reflect the CURRENT turn, not the
    # previous one.
    assert "(nothing yet)" not in profile_json


def test_typo_corrections_are_shown_in_chat():
    at = fresh_app()
    at.chat_input[0].set_value(
        "I'm 65 years old, live in gujrat, and work as a tacher"
    ).run()
    assert not at.exception
    messages = [message.markdown[0].value for message in at.chat_message]
    assert any("gujrat" in message and "gujarat" in message for message in messages)
    assert any("tacher" in message and "teacher" in message for message in messages)


def test_hard_fail_shows_not_eligible_without_asking_more():
    at = fresh_app()
    # Occupation ("teacher") included so PM-KISAN also resolves in one
    # turn (it needs occupation info) rather than triggering another
    # clarifying question and leaving results unrendered this turn.
    at.chat_input[0].set_value(
        "I'm 40 years old, live in Gujarat, work as a teacher, annual income is 1 lakh rupees"
    ).run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any("Vay Vandana" in l and "Not eligible" in l for l in labels)


def test_start_over_resets_everything():
    at = fresh_app()
    at.chat_input[0].set_value("I am 65 years old and live in Gujarat").run()
    assert len(at.chat_message) > 1

    at.button[0].click().run()
    assert not at.exception
    assert len(at.chat_message) == 1  # back to just the greeting
    assert len(at.expander) == 0
    assert "(nothing yet)" in at.sidebar.json[0].value


def test_no_duplicate_result_cards():
    at = fresh_app()
    at.chat_input[0].set_value(
        "I'm 40 years old, live in Gujarat, work as a teacher, annual income is 1 lakh rupees"
    ).run()
    assert not at.exception
    # 3 schemes in the sample dataset -> exactly 3 expanders, not 6.
    assert len(at.expander) == 3


if __name__ == "__main__":
    test_app_boots_with_greeting()
    test_multi_turn_conversation_reaches_eligible_verdict()
    test_sidebar_profile_updates_immediately_not_lagged()
    test_typo_corrections_are_shown_in_chat()
    test_hard_fail_shows_not_eligible_without_asking_more()
    test_start_over_resets_everything()
    test_no_duplicate_result_cards()
    print("\nALL TESTS PASSED")
