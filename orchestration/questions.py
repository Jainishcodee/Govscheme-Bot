"""
Maps a rule-engine condition field name (see rule_engine/engine.py's
ConditionResult.field values) to a natural-language question. Kept as
plain templates rather than an LLM call — Module 6 is where an LLM
enters the pipeline, and even then only to rephrase pre-computed
facts, never to invent what to ask. A fixed template set is also just
easier to test deterministically.
"""

from typing import Dict


QUESTION_TEMPLATES: Dict[str, str] = {
    "age": "Could you tell me your age?",
    "annual_income": "What's your family's approximate annual income (in Rs.)?",
    "gender": "Could you tell me your gender?",
    "caste_category": "Which caste category do you belong to (General/OBC/SC/ST/EWS)?",
    "marital_status": "What's your marital status?",
    "state": "Which state do you live in?",
    "occupation": "What's your occupation?",
    "disability_status": "Do you have a disability?",
    "bpl_required": "Do you hold a BPL (Below Poverty Line) card?",
}


def question_for_field(field_name: str) -> str:
    return QUESTION_TEMPLATES.get(
        field_name, f"Could you provide more information about {field_name.replace('_', ' ')}?"
    )
