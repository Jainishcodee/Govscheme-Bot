"""
Turns free text like "I'm a 62 year old widow farmer in Gujarat with
no income" into a structured UserProfile.

Two different techniques, deliberately:

  - AGE and INCOME are extracted with regex. Numbers with units
    ("2 lakh", "Rs. 1,50,000", "62 years old") are a poor fit for a
    generic NER model and a good fit for a few well-chosen patterns —
    same reasoning as the hand-rolled rule engine: something you can
    fully explain in a viva beats a black box, at this scale.

  - Everything categorical (gender, marital status, caste category,
    state, occupation, disability, BPL status) is extracted with a
    spaCy PhraseMatcher over a blank English pipeline. This is the
    "rule-based matcher" option from the project plan (as opposed to
    training a custom NER model, which needs labeled data you don't
    have yet). No pretrained spaCy model is downloaded — the blank
    pipeline's tokenizer is all PhraseMatcher needs.

This is Module 4's whole job: text -> UserProfile. It does NOT decide
eligibility — that's still entirely the rule engine's job (Module 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import spacy
from spacy.matcher import PhraseMatcher

from nlp_extraction import lookups
from rule_engine.user_profile import UserProfile

_NLP = spacy.blank("en")


def _build_matcher(term_map: Dict[str, str]) -> PhraseMatcher:
    matcher = PhraseMatcher(_NLP.vocab, attr="LOWER")
    patterns = [_NLP.make_doc(surface) for surface in term_map]
    matcher.add("TERM", patterns)
    return matcher


def _build_list_matcher(terms: List[str]) -> PhraseMatcher:
    matcher = PhraseMatcher(_NLP.vocab, attr="LOWER")
    patterns = [_NLP.make_doc(t) for t in terms]
    matcher.add("TERM", patterns)
    return matcher


# Built once at import time — reused across every extract() call.
_STATE_MATCHER = _build_list_matcher(lookups.INDIAN_STATES)
_OCCUPATION_MATCHER = _build_matcher(lookups.OCCUPATION_TERMS)
_CASTE_MATCHER = _build_matcher(lookups.CASTE_TERMS)
_MARITAL_MATCHER = _build_matcher(lookups.MARITAL_TERMS)
_GENDER_MATCHER = _build_matcher(lookups.GENDER_TERMS)
_DISABILITY_MATCHER = _build_list_matcher(lookups.DISABILITY_TERMS)
_BPL_MATCHER = _build_list_matcher(lookups.BPL_TERMS)


# --- age ---------------------------------------------------------------

_AGE_PATTERNS = [
    re.compile(r"\b(\d{1,3})\s*[-\s]?year[-\s]?old\b", re.I),
    re.compile(r"\bage(?:d)?\s*(?:is|:|of)?\s*(\d{1,3})\b", re.I),
    re.compile(r"\bi\s*(?:'m|am)\s*(\d{1,3})\b", re.I),
    re.compile(r"\b(\d{1,3})\s*yrs?\b", re.I),
]


def _extract_age(text: str) -> Tuple[Optional[int], Optional[str]]:
    for pattern in _AGE_PATTERNS:
        m = pattern.search(text)
        if m:
            age = int(m.group(1))
            if 0 < age <= 120:
                return age, m.group(0)
    return None, None


# --- income --------------------------------------------------------------

_LAKH_RE = re.compile(r"\b([\d,]+(?:\.\d+)?)\s*lakhs?\b", re.I)
_CURRENCY_RE = re.compile(r"(?:rs\.?|inr|rupees)\s*([\d,]+(?:\.\d+)?)", re.I)
_CONTEXT_RE = re.compile(
    r"(?:income|earns?|salary|earning)\D{0,15}?([\d,]+(?:\.\d+)?)", re.I
)
_MONTHLY_RE = re.compile(r"\b(?:per\s*month|monthly|/\s*month|a\s*month)\b", re.I)


def _to_number(s: str) -> float:
    return float(s.replace(",", ""))


def _extract_income(text: str) -> Tuple[Optional[int], Optional[str]]:
    match = _LAKH_RE.search(text)
    if match:
        value = _to_number(match.group(1)) * 100_000
        raw = match.group(0)
    else:
        match = _CURRENCY_RE.search(text) or _CONTEXT_RE.search(text)
        if not match:
            return None, None
        value = _to_number(match.group(1))
        raw = match.group(0)

    if _MONTHLY_RE.search(text):
        value *= 12

    return int(value), raw


# --- categorical fields via PhraseMatcher --------------------------------

def _first_match(matcher: PhraseMatcher, doc, value_lookup: Optional[Dict[str, str]] = None):
    """
    Return (normalized_value, raw_matched_text) for the earliest match
    in the doc, or (None, None). `value_lookup` maps surface text
    (lowercase) -> normalized value; if omitted, the matched span's
    own lowercased text is returned as the "normalized" value (used
    for the plain state list, which is already normalized).
    """
    matches = matcher(doc)
    if not matches:
        return None, None
    matches = sorted(matches, key=lambda m: m[1])  # earliest start first
    match_id, start, end = matches[0]
    span_text = doc[start:end].text.lower()
    if value_lookup is not None:
        return value_lookup[span_text], doc[start:end].text
    return span_text, doc[start:end].text


@dataclass
class ExtractionResult:
    profile: UserProfile
    # field name -> raw text span that produced it, for debugging /
    # for showing the user "here's what I understood" transparency.
    matched_spans: Dict[str, str] = field(default_factory=dict)
    # Typo correction transparency: the text after auto-correction,
    # plus each distinct (original, corrected) pair applied. Empty
    # when nothing needed fixing. The UI surfaces this as
    # "I read 'gujrat' as 'gujarat'" so the user can spot a bad fix.
    corrected_text: str = ""
    corrections: List[Tuple[str, str]] = field(default_factory=list)


def extract(text: str, correct_typos: bool = True) -> ExtractionResult:
    # Auto-correct vocabulary typos ("tacher" -> "teacher", "gujrat"
    # -> "gujarat") BEFORE any matching runs, so the PhraseMatcher
    # and the regexes both see clean text. Correction is conservative
    # by design (see spelling.py) — when in doubt it leaves the token
    # alone rather than guessing.
    corrections: List[Tuple[str, str]] = []
    working_text = text
    if correct_typos:
        try:
            from spelling import domain_corrector

            working_text, corrections = domain_corrector().correct_text(text)
        except Exception:
            # Never let a spelling helper break extraction — fall back
            # to the raw text.
            working_text, corrections = text, []

    doc = _NLP(working_text)
    matched: Dict[str, str] = {}

    age, raw = _extract_age(working_text)
    if raw:
        matched["age"] = raw

    income, raw = _extract_income(working_text)
    if raw:
        matched["annual_income"] = raw

    state, raw = _first_match(_STATE_MATCHER, doc)
    if raw:
        matched["state"] = raw

    occupation, raw = _first_match(_OCCUPATION_MATCHER, doc, lookups.OCCUPATION_TERMS)
    if raw:
        matched["occupation"] = raw

    caste_category, raw = _first_match(_CASTE_MATCHER, doc, lookups.CASTE_TERMS)
    if raw:
        matched["caste_category"] = raw

    marital_status, raw = _first_match(_MARITAL_MATCHER, doc, lookups.MARITAL_TERMS)
    if raw:
        matched["marital_status"] = raw

    gender, raw = _first_match(_GENDER_MATCHER, doc, lookups.GENDER_TERMS)
    if raw:
        matched["gender"] = raw

    _, disability_raw = _first_match(_DISABILITY_MATCHER, doc)
    has_disability = True if disability_raw else None
    if disability_raw:
        matched["has_disability"] = disability_raw

    _, bpl_raw = _first_match(_BPL_MATCHER, doc)
    has_bpl_card = True if bpl_raw else None
    if bpl_raw:
        matched["has_bpl_card"] = bpl_raw

    profile = UserProfile(
        age=age,
        annual_income=income,
        gender=gender,
        caste_category=caste_category,
        marital_status=marital_status,
        state=state,
        occupation=occupation,
        has_disability=has_disability,
        has_bpl_card=has_bpl_card,
    )
    return ExtractionResult(
        profile=profile,
        matched_spans=matched,
        corrected_text=working_text,
        corrections=corrections,
    )


def merge_profile(existing: UserProfile, new: UserProfile) -> UserProfile:
    """
    Incremental slot-filling for multi-turn conversations: a newly
    extracted field overwrites a previously-known one only if the new
    extraction actually found something. Existing non-null fields are
    preserved when the new turn didn't mention them at all — the user
    doesn't have to repeat everything they've already told the bot.
    """
    merged = existing.model_copy()
    for field_name in UserProfile.model_fields:
        new_value = getattr(new, field_name)
        if new_value is not None:
            setattr(merged, field_name, new_value)
    return merged
