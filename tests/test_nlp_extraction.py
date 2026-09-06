"""
Run with: python3 tests/test_nlp_extraction.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nlp_extraction.extractor import extract, merge_profile  # noqa: E402
from rule_engine.user_profile import UserProfile  # noqa: E402


def show(text, result):
    print(f"\nTEXT: {text!r}")
    print(f"  -> {result.profile.model_dump(exclude_none=True)}")
    print(f"  matched on: {result.matched_spans}")


def test_project_plan_example():
    # The exact example from the project plan's Phase 4 description.
    text = "I'm a 62-year-old widow farmer in Gujarat with no income"
    result = extract(text)
    show(text, result)
    p = result.profile
    assert p.age == 62
    assert p.gender == "female"        # inferred from "widow"
    assert p.marital_status == "widowed"
    assert p.occupation == "farmer"
    assert p.state == "gujarat"
    # "no income" isn't parsed as a number — that's a genuine gap,
    # see README for how the clarifying-question loop should handle it


def test_income_lakh():
    text = "My annual family income is around 2 lakh rupees"
    result = extract(text)
    show(text, result)
    assert result.profile.annual_income == 200_000


def test_income_monthly_conversion():
    text = "I earn 15000 per month as a driver in Maharashtra"
    result = extract(text)
    show(text, result)
    assert result.profile.annual_income == 180_000  # 15000 * 12
    assert result.profile.occupation == "driver"
    assert result.profile.state == "maharashtra"


def test_income_currency_symbol():
    text = "Family income is Rs. 1,50,000 annually"
    result = extract(text)
    show(text, result)
    assert result.profile.annual_income == 150_000


def test_caste_and_disability_and_bpl():
    text = "I belong to the OBC category, have a disability, and hold a BPL card"
    result = extract(text)
    show(text, result)
    assert result.profile.caste_category == "obc"
    assert result.profile.has_disability is True
    assert result.profile.has_bpl_card is True


def test_no_matches_returns_empty_profile():
    text = "Hello, can you help me?"
    result = extract(text)
    show(text, result)
    assert result.profile.age is None
    assert result.matched_spans == {}


def test_merge_profile_incremental():
    turn1 = extract("I am 45 years old and live in Kerala")
    turn2 = extract("I work as a teacher")
    merged = merge_profile(turn1.profile, turn2.profile)
    print(f"\nMerged: {merged.model_dump(exclude_none=True)}")
    assert merged.age == 45          # preserved from turn 1
    assert merged.state == "kerala"  # preserved from turn 1
    assert merged.occupation == "teacher"  # added in turn 2

    # turn 3 corrects the state — should overwrite, not merge-fail
    turn3 = extract("Actually I live in Tamil Nadu now")
    merged2 = merge_profile(merged, turn3.profile)
    assert merged2.state == "tamil nadu"
    assert merged2.age == 45  # still preserved


if __name__ == "__main__":
    test_project_plan_example()
    test_income_lakh()
    test_income_monthly_conversion()
    test_income_currency_symbol()
    test_caste_and_disability_and_bpl()
    test_no_matches_returns_empty_profile()
    test_merge_profile_incremental()
    print("\nALL TESTS PASSED")
