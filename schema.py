"""
Structured data schema for the Government Scheme Eligibility Chatbot.

Design principle (per project plan): the rule engine reads ONLY the
structured `EligibilityCriteria` fields below. Free-text `description`
is what gets embedded for RAG. Never let the LLM infer eligibility from
prose — it only ever explains a decision the rule engine already made.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    ANY = "any"  # scheme has no gender restriction


class CasteCategory(str, Enum):
    GENERAL = "general"
    OBC = "obc"
    SC = "sc"
    ST = "st"
    EWS = "ews"
    ANY = "any"


class MaritalStatus(str, Enum):
    MARRIED = "married"
    UNMARRIED = "unmarried"
    WIDOWED = "widowed"
    ANY = "any"


class EligibilityCriteria(BaseModel):
    """
    Every field is Optional[...] = None, and None means "this scheme
    does not restrict on this dimension" — NOT "unknown". That
    distinction matters for the rule engine (Module 3): a None field
    should always evaluate as PASS, never as MISSING_INFO.

    Fields with real-world values close over the user's profile with
    inclusive bounds: age_min <= user.age <= age_max.
    """

    age_min: Optional[int] = Field(None, ge=0, le=120)
    age_max: Optional[int] = Field(None, ge=0, le=120)

    income_min: Optional[int] = Field(None, ge=0, description="Annual family income, INR")
    income_max: Optional[int] = Field(None, ge=0, description="Annual family income, INR")

    gender: Optional[Gender] = None
    caste_category: Optional[List[CasteCategory]] = None  # scheme may allow several
    marital_status: Optional[MaritalStatus] = None

    # State names should be normalized lowercase, e.g. "gujarat".
    # None = central/all-India scheme (no state restriction).
    state: Optional[List[str]] = None

    occupation: Optional[List[str]] = None  # e.g. ["farmer", "landless_laborer"]
    disability_status: Optional[bool] = None  # True = disability required
    bpl_required: Optional[bool] = None  # True = must hold BPL card

    # Anything the rule engine can't structure yet (rare, edge-case
    # conditions). Surfaced to the user verbatim in explanations rather
    # than silently dropped.
    additional_conditions: Optional[List[str]] = None

    @field_validator("age_max")
    @classmethod
    def age_max_not_below_min(cls, v, info):
        age_min = info.data.get("age_min")
        if v is not None and age_min is not None and v < age_min:
            raise ValueError("age_max cannot be less than age_min")
        return v

    @field_validator("income_max")
    @classmethod
    def income_max_not_below_min(cls, v, info):
        income_min = info.data.get("income_min")
        if v is not None and income_min is not None and v < income_min:
            raise ValueError("income_max cannot be less than income_min")
        return v


class SchemeCategory(str, Enum):
    AGRICULTURE = "agriculture"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    HOUSING = "housing"
    PENSION = "pension"
    EMPLOYMENT = "employment"
    WOMEN_CHILD = "women_and_child"
    DISABILITY = "disability"
    OTHER = "other"


class Scheme(BaseModel):
    scheme_id: str = Field(..., description="Stable slug, e.g. 'pm-kisan'")
    name: str
    description: str = Field(..., description="Free text — this is what gets embedded for RAG")
    department: str
    category: SchemeCategory

    eligibility: EligibilityCriteria

    benefits: str
    documents_required: List[str] = Field(default_factory=list)

    application_link: Optional[HttpUrl] = None
    source_url: HttpUrl

    # Versioning fields (per project design recommendation:
    # "Version your scheme data. Government schemes change; log
    # when a scheme's criteria were last verified.")
    last_verified: date
    verified_by: str = Field(
        default="unverified",
        description="'manual' | 'llm_assisted' | 'unverified' — how eligibility JSON was produced",
    )

    model_config = ConfigDict(use_enum_values=True)


if __name__ == "__main__":
    # Quick smoke test
    s = Scheme(
        scheme_id="test-scheme",
        name="Test Scheme",
        description="A scheme for testing the schema.",
        department="Test Dept",
        category=SchemeCategory.PENSION,
        eligibility=EligibilityCriteria(age_min=60, income_max=200_000, state=["gujarat"]),
        benefits="Rs. 1000/month",
        documents_required=["Aadhaar", "Income certificate"],
        source_url="https://example.gov.in/test-scheme",
        last_verified=date(2026, 8, 19),
        verified_by="manual",
    )
    print(s.model_dump_json(indent=2))
