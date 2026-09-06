"""
Run with: python3 tests/test_explanation.py

Tests TemplateExplanationGenerator against real eligibility results
(all four status types), and LLMExplanationGenerator's wiring using a
fake llm_call — no network, no API key, but genuinely verifies the
prompt is built correctly and the response is handled/parsed
correctly.
"""

import json
import os
import sys
from typing import Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import Scheme  # noqa: E402
from rule_engine.engine import evaluate_scheme  # noqa: E402
from rule_engine.user_profile import UserProfile  # noqa: E402
from explanation.generator import (  # noqa: E402
    LLMExplanationGenerator,
    TemplateExplanationGenerator,
    build_prompt,
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_schemes.json")


def load_schemes() -> Dict[str, Scheme]:
    with open(DATA_PATH) as f:
        raw = json.load(f)
    return {s["scheme_id"]: Scheme(**s) for s in raw}


def test_template_eligible():
    schemes = load_schemes()
    profile = UserProfile(age=65, annual_income=100_000, state="gujarat")
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)
    text = TemplateExplanationGenerator().generate(result)
    print("\nELIGIBLE:", text)
    assert "ELIGIBLE" in text and "NOT ELIGIBLE" not in text
    assert result.scheme_name in text


def test_template_not_eligible():
    schemes = load_schemes()
    profile = UserProfile(age=45, annual_income=100_000, state="gujarat")
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)
    text = TemplateExplanationGenerator().generate(result)
    print("NOT_ELIGIBLE:", text)
    assert "NOT ELIGIBLE" in text
    assert "60" in text  # the failing age threshold should surface


def test_template_partially_eligible():
    schemes = load_schemes()
    profile = UserProfile(age=65, state="gujarat")  # income missing
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)
    text = TemplateExplanationGenerator().generate(result)
    print("PARTIALLY_ELIGIBLE:", text)
    assert "more information" in text.lower() or "income" in text.lower()


def test_template_needs_manual_review():
    schemes = load_schemes()
    profile = UserProfile(occupation="farmer")
    result = evaluate_scheme(schemes["pm-kisan"], profile)
    text = TemplateExplanationGenerator().generate(result)
    print("NEEDS_MANUAL_REVIEW:", text)
    assert "manual verification" in text.lower() or "manually" in text.lower()
    assert "landholding" in text.lower()  # one of PM-KISAN's additional_conditions


def test_prompt_is_grounded_and_forbids_invention():
    schemes = load_schemes()
    profile = UserProfile(age=45, annual_income=100_000, state="gujarat")
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)
    prompt = build_prompt(result)
    print("\nPROMPT:\n", prompt)
    assert "Vay Vandana" in prompt
    assert "not_eligible" in prompt
    assert "invent" in prompt.lower()
    assert "60" in prompt  # the actual failing threshold must be present for grounding


def test_llm_generator_uses_fake_callable():
    schemes = load_schemes()
    profile = UserProfile(age=65, annual_income=100_000, state="gujarat")
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)

    captured_prompts = []

    def fake_llm_call(prompt: str) -> str:
        captured_prompts.append(prompt)
        return "You're all set for the Vay Vandana pension — every requirement checks out!"

    generator = LLMExplanationGenerator(llm_call=fake_llm_call)
    text = generator.generate(result)
    print("\nLLM (fake) response:", text)

    assert text == "You're all set for the Vay Vandana pension — every requirement checks out!"
    assert len(captured_prompts) == 1
    assert "Vay Vandana" in captured_prompts[0]


def test_llm_generator_falls_back_on_error():
    schemes = load_schemes()
    profile = UserProfile(age=45, annual_income=100_000, state="gujarat")
    result = evaluate_scheme(schemes["vay-vandana-yojana-gujarat"], profile)

    def broken_llm_call(prompt: str) -> str:
        raise ConnectionError("simulated network failure")

    generator = LLMExplanationGenerator(llm_call=broken_llm_call)
    text = generator.generate(result)
    print("Fallback after simulated failure:", text)
    # Should silently fall back to the template generator, not crash.
    assert "NOT ELIGIBLE" in text


def test_generate_all():
    schemes = load_schemes()
    profile = UserProfile(age=65, annual_income=100_000, state="gujarat", occupation="farmer")
    results = [evaluate_scheme(s, profile) for s in schemes.values()]
    explanations = TemplateExplanationGenerator().generate_all(results)
    assert set(explanations.keys()) == set(schemes.keys())
    assert all(isinstance(v, str) and v for v in explanations.values())


if __name__ == "__main__":
    test_template_eligible()
    test_template_not_eligible()
    test_template_partially_eligible()
    test_template_needs_manual_review()
    test_prompt_is_grounded_and_forbids_invention()
    test_llm_generator_uses_fake_callable()
    test_llm_generator_falls_back_on_error()
    test_generate_all()
    print("\nALL TESTS PASSED")
