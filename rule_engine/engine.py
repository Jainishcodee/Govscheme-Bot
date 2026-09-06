"""
The rule engine. Deterministic, transparent, no LLM in the loop.

Core contract: evaluate_scheme(scheme, profile) -> EligibilityResult,
which contains a PASS/FAIL/MISSING_INFO/NEEDS_REVIEW verdict for every
individual condition, plus one overall EligibilityStatus. The
explanation-generation LLM (Phase 6) only ever rephrases this
structured output into prose — it never makes the eligible/not-eligible
call itself.

Per-condition semantics:
  PASS          - criterion is None (unrestricted) or satisfied
  FAIL          - criterion is set and user's value violates it
  MISSING_INFO  - criterion is set but the user hasn't provided the
                  matching profile field yet
  NEEDS_REVIEW  - only for `additional_conditions`: free-text criteria
                  the engine cannot evaluate mechanically at all

Overall status priority (worst wins):
  1. NOT_ELIGIBLE          - any condition FAILed
  2. PARTIALLY_ELIGIBLE    - no fails, but info missing to decide
  3. NEEDS_MANUAL_REVIEW   - all structured conditions pass, but the
                             scheme has additional_conditions that
                             can't be auto-checked
  4. ELIGIBLE              - everything structured passes, nothing
                             left to review
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from schema import EligibilityCriteria, Scheme
from rule_engine.user_profile import UserProfile


class ConditionStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    MISSING_INFO = "missing_info"
    NEEDS_REVIEW = "needs_review"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    PARTIALLY_ELIGIBLE = "partially_eligible"  # missing info blocks a decision
    NEEDS_MANUAL_REVIEW = "needs_manual_review"  # structured checks pass; free-text conditions remain


class ConditionResult(BaseModel):
    field: str
    status: ConditionStatus
    message: str


class EligibilityResult(BaseModel):
    scheme_id: str
    scheme_name: str
    status: EligibilityStatus
    conditions: List[ConditionResult]

    @property
    def failed_conditions(self) -> List[ConditionResult]:
        return [c for c in self.conditions if c.status == ConditionStatus.FAIL]

    @property
    def missing_fields(self) -> List[str]:
        return [c.field for c in self.conditions if c.status == ConditionStatus.MISSING_INFO]


# --- individual condition checkers -----------------------------------
# Each takes (criteria, profile) and returns a ConditionResult or None.
# Returning None means "not applicable to this scheme" — it's simply
# omitted from the results list rather than shown as a trivial PASS,
# to keep the per-scheme output focused on conditions that actually
# constrain this scheme.

def _check_age(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if c.age_min is None and c.age_max is None:
        return None
    if p.age is None:
        bound = f"{c.age_min or 0}-{c.age_max or '∞'}"
        return ConditionResult(
            field="age", status=ConditionStatus.MISSING_INFO,
            message=f"Scheme requires age in range {bound}; user's age is unknown."
        )
    if c.age_min is not None and p.age < c.age_min:
        return ConditionResult(
            field="age", status=ConditionStatus.FAIL,
            message=f"Requires age >= {c.age_min}, user is {p.age}."
        )
    if c.age_max is not None and p.age > c.age_max:
        return ConditionResult(
            field="age", status=ConditionStatus.FAIL,
            message=f"Requires age <= {c.age_max}, user is {p.age}."
        )
    return ConditionResult(
        field="age", status=ConditionStatus.PASS,
        message=f"Age {p.age} satisfies scheme requirement."
    )


def _check_income(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if c.income_min is None and c.income_max is None:
        return None
    if p.annual_income is None:
        return ConditionResult(
            field="annual_income", status=ConditionStatus.MISSING_INFO,
            message="Scheme has an income criterion; user's annual income is unknown."
        )
    if c.income_min is not None and p.annual_income < c.income_min:
        return ConditionResult(
            field="annual_income", status=ConditionStatus.FAIL,
            message=f"Requires income >= Rs.{c.income_min}, user has Rs.{p.annual_income}."
        )
    if c.income_max is not None and p.annual_income > c.income_max:
        return ConditionResult(
            field="annual_income", status=ConditionStatus.FAIL,
            message=f"Requires income <= Rs.{c.income_max}, user has Rs.{p.annual_income}."
        )
    return ConditionResult(
        field="annual_income", status=ConditionStatus.PASS,
        message=f"Income Rs.{p.annual_income} satisfies scheme requirement."
    )


def _check_gender(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if c.gender is None or c.gender == "any":
        return None
    if p.gender is None:
        return ConditionResult(
            field="gender", status=ConditionStatus.MISSING_INFO,
            message=f"Scheme requires gender = {c.gender}; user's gender is unknown."
        )
    if p.gender != c.gender:
        return ConditionResult(
            field="gender", status=ConditionStatus.FAIL,
            message=f"Requires gender = {c.gender}, user is {p.gender}."
        )
    return ConditionResult(
        field="gender", status=ConditionStatus.PASS,
        message="Gender matches scheme requirement."
    )


def _check_caste_category(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if not c.caste_category or "any" in c.caste_category:
        return None
    if p.caste_category is None:
        return ConditionResult(
            field="caste_category", status=ConditionStatus.MISSING_INFO,
            message=f"Scheme restricts to {c.caste_category}; user's category is unknown."
        )
    if p.caste_category not in c.caste_category:
        return ConditionResult(
            field="caste_category", status=ConditionStatus.FAIL,
            message=f"Requires category in {c.caste_category}, user is {p.caste_category}."
        )
    return ConditionResult(
        field="caste_category", status=ConditionStatus.PASS,
        message="Caste category matches scheme requirement."
    )


def _check_marital_status(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if c.marital_status is None or c.marital_status == "any":
        return None
    if p.marital_status is None:
        return ConditionResult(
            field="marital_status", status=ConditionStatus.MISSING_INFO,
            message=f"Scheme requires marital status = {c.marital_status}; unknown for user."
        )
    if p.marital_status != c.marital_status:
        return ConditionResult(
            field="marital_status", status=ConditionStatus.FAIL,
            message=f"Requires marital status = {c.marital_status}, user is {p.marital_status}."
        )
    return ConditionResult(
        field="marital_status", status=ConditionStatus.PASS,
        message="Marital status matches scheme requirement."
    )


def _check_state(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if not c.state:
        return None  # None/empty = central scheme, no state restriction
    if p.state is None:
        return ConditionResult(
            field="state", status=ConditionStatus.MISSING_INFO,
            message=f"Scheme is restricted to {c.state}; user's state is unknown."
        )
    if p.state.lower() not in [s.lower() for s in c.state]:
        return ConditionResult(
            field="state", status=ConditionStatus.FAIL,
            message=f"Requires state in {c.state}, user is in {p.state}."
        )
    return ConditionResult(
        field="state", status=ConditionStatus.PASS,
        message="State matches scheme requirement."
    )


def _check_occupation(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if not c.occupation:
        return None
    if p.occupation is None:
        return ConditionResult(
            field="occupation", status=ConditionStatus.MISSING_INFO,
            message=f"Scheme is restricted to occupations {c.occupation}; user's occupation is unknown."
        )
    if p.occupation.lower() not in [o.lower() for o in c.occupation]:
        return ConditionResult(
            field="occupation", status=ConditionStatus.FAIL,
            message=f"Requires occupation in {c.occupation}, user is {p.occupation}."
        )
    return ConditionResult(
        field="occupation", status=ConditionStatus.PASS,
        message="Occupation matches scheme requirement."
    )


def _check_disability(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if c.disability_status is None:
        return None
    if p.has_disability is None:
        return ConditionResult(
            field="disability_status", status=ConditionStatus.MISSING_INFO,
            message="Scheme has a disability requirement; unknown for user."
        )
    if p.has_disability != c.disability_status:
        return ConditionResult(
            field="disability_status", status=ConditionStatus.FAIL,
            message=f"Requires disability_status = {c.disability_status}, user is {p.has_disability}."
        )
    return ConditionResult(
        field="disability_status", status=ConditionStatus.PASS,
        message="Disability status matches scheme requirement."
    )


def _check_bpl(c: EligibilityCriteria, p: UserProfile) -> Optional[ConditionResult]:
    if c.bpl_required is None or c.bpl_required is False:
        return None
    if p.has_bpl_card is None:
        return ConditionResult(
            field="bpl_required", status=ConditionStatus.MISSING_INFO,
            message="Scheme requires a BPL card; unknown whether user has one."
        )
    if not p.has_bpl_card:
        return ConditionResult(
            field="bpl_required", status=ConditionStatus.FAIL,
            message="Scheme requires a BPL card; user does not have one."
        )
    return ConditionResult(
        field="bpl_required", status=ConditionStatus.PASS,
        message="User holds a BPL card as required."
    )


_STRUCTURED_CHECKS = [
    _check_age,
    _check_income,
    _check_gender,
    _check_caste_category,
    _check_marital_status,
    _check_state,
    _check_occupation,
    _check_disability,
    _check_bpl,
]

# Overall status priority: lower index = "worse" outcome, wins ties.
_STATUS_PRIORITY = [
    EligibilityStatus.NOT_ELIGIBLE,
    EligibilityStatus.PARTIALLY_ELIGIBLE,
    EligibilityStatus.NEEDS_MANUAL_REVIEW,
    EligibilityStatus.ELIGIBLE,
]


def evaluate_scheme(scheme: Scheme, profile: UserProfile) -> EligibilityResult:
    conditions: List[ConditionResult] = []

    for check in _STRUCTURED_CHECKS:
        result = check(scheme.eligibility, profile)
        if result is not None:
            conditions.append(result)

    for cond_text in (scheme.eligibility.additional_conditions or []):
        conditions.append(ConditionResult(
            field="additional_condition",
            status=ConditionStatus.NEEDS_REVIEW,
            message=cond_text,
        ))

    has_fail = any(c.status == ConditionStatus.FAIL for c in conditions)
    has_missing = any(c.status == ConditionStatus.MISSING_INFO for c in conditions)
    has_review = any(c.status == ConditionStatus.NEEDS_REVIEW for c in conditions)

    if has_fail:
        status = EligibilityStatus.NOT_ELIGIBLE
    elif has_missing:
        status = EligibilityStatus.PARTIALLY_ELIGIBLE
    elif has_review:
        status = EligibilityStatus.NEEDS_MANUAL_REVIEW
    else:
        status = EligibilityStatus.ELIGIBLE

    return EligibilityResult(
        scheme_id=scheme.scheme_id,
        scheme_name=scheme.name,
        status=status,
        conditions=conditions,
    )


def evaluate_all(schemes: List[Scheme], profile: UserProfile) -> List[EligibilityResult]:
    """Evaluate every scheme, sorted best-outcome-first for display."""
    results = [evaluate_scheme(s, profile) for s in schemes]
    return sorted(results, key=lambda r: _STATUS_PRIORITY.index(r.status))
