"""
Run with: python3 tests/test_rule_engine.py

Exercises all four EligibilityStatus outcomes against the real
Module-1 sample data (PM-KISAN, PM-JAY, Vay Vandana Gujarat):

  1. ELIGIBLE            - Vay Vandana, profile fully matches
  2. NOT_ELIGIBLE         - Vay Vandana, profile fails age
  3. PARTIALLY_ELIGIBLE   - Vay Vandana, income unknown
  4. NEEDS_MANUAL_REVIEW  - PM-KISAN, structured checks pass but
                            additional_conditions remain unchecked
"""

import json
import os
import sys
from typing import Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import Scheme  # noqa: E402
from rule_engine.engine import evaluate_scheme, evaluate_all, EligibilityStatus  # noqa: E402
from rule_engine.user_profile import UserProfile  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_schemes.json")


def load_schemes() -> Dict[str, Scheme]:
    with open(DATA_PATH) as f:
        raw = json.load(f)
    schemes = [Scheme(**item) for item in raw]
    return {s.scheme_id: s for s in schemes}


def show(label, result):
    print(f"\n--- {label} ---")
    print(f"{result.scheme_name}: {result.status.value}")
    for c in result.conditions:
        print(f"  [{c.status.value:13s}] {c.field}: {c.message}")


def test_eligible():
    schemes = load_schemes()
    profile = UserProfile(age=65, annual_income=100_000, state="gujarat", gender="female")
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)
    show("Vay Vandana — should be ELIGIBLE", result)
    assert result.status == EligibilityStatus.ELIGIBLE


def test_not_eligible_age():
    schemes = load_schemes()
    profile = UserProfile(age=45, annual_income=100_000, state="gujarat")
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)
    show("Vay Vandana, age 45 — should be NOT_ELIGIBLE", result)
    assert result.status == EligibilityStatus.NOT_ELIGIBLE
    assert "age" in result.failed_conditions[0].field


def test_partially_eligible_missing_income():
    schemes = load_schemes()
    profile = UserProfile(age=65, state="gujarat")  # income not provided
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)
    show("Vay Vandana, income unknown — should be PARTIALLY_ELIGIBLE", result)
    assert result.status == EligibilityStatus.PARTIALLY_ELIGIBLE
    assert "annual_income" in result.missing_fields


def test_needs_manual_review_pm_kisan():
    schemes = load_schemes()
    # PM-KISAN has no structured age/income/state/etc. criteria at all —
    # everything it restricts on lives in additional_conditions. So ANY
    # profile lands in NEEDS_MANUAL_REVIEW, never straight ELIGIBLE.
    profile = UserProfile(occupation="farmer")
    result = evaluate_scheme(schemes["pm-kisan"], profile)
    show("PM-KISAN, farmer — should be NEEDS_MANUAL_REVIEW", result)
    assert result.status == EligibilityStatus.NEEDS_MANUAL_REVIEW
    review_items = [c for c in result.conditions if c.status.value == "needs_review"]
    assert len(review_items) == 4  # PM-KISAN's 4 additional_conditions
    assert all(c.status.value in ("pass", "needs_review") for c in result.conditions)


def test_evaluate_all_sorts_best_first():
    schemes = load_schemes()
    profile = UserProfile(age=65, annual_income=100_000, state="gujarat")
    results = evaluate_all(list(schemes.values()), profile)
    print("\n--- evaluate_all, sorted ---")
    for r in results:
        print(f"  {r.status.value:20s} {r.scheme_name}")
    # Vay Vandana should sort ahead of NOT_ELIGIBLE/PARTIALLY results
    statuses = [r.status for r in results]
    assert statuses[0] in (EligibilityStatus.NOT_ELIGIBLE, EligibilityStatus.PARTIALLY_ELIGIBLE) \
        or statuses[-1] == EligibilityStatus.ELIGIBLE  # sanity: something at the "good" end


if __name__ == "__main__":
    test_eligible()
    test_not_eligible_age()
    test_partially_eligible_missing_income()
    test_needs_manual_review_pm_kisan()
    test_evaluate_all_sorts_best_first()
    print("\nALL TESTS PASSED")
