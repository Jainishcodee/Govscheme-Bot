"""
Structured user profile the rule engine evaluates against.

Every field is Optional because a real conversation fills this in
incrementally — a user rarely states age, income, state, occupation,
gender, caste category, marital status, disability, and BPL status
all in one message. The engine has to work correctly against a
*partially filled* profile, which is exactly why it needs a distinct
MISSING_INFO outcome (see engine.py) rather than just PASS/FAIL.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from schema import CasteCategory, Gender, MaritalStatus


class UserProfile(BaseModel):
    age: Optional[int] = None
    annual_income: Optional[int] = None  # INR, family income
    gender: Optional[Gender] = None
    caste_category: Optional[CasteCategory] = None
    marital_status: Optional[MaritalStatus] = None
    state: Optional[str] = None  # normalized lowercase, e.g. "gujarat"
    occupation: Optional[str] = None  # normalized lowercase, e.g. "farmer"
    has_disability: Optional[bool] = None
    has_bpl_card: Optional[bool] = None
