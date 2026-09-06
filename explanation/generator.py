"""
Turns an already-decided EligibilityResult into natural-language
explanation text. Two implementations sharing one interface:

  - TemplateExplanationGenerator: deterministic string templates.
    No API key, no network, fully offline-testable. This is the
    DEFAULT — the demo and every automated test use it, so grading /
    running this project never depends on having an LLM API key.

  - LLMExplanationGenerator: sends the SAME structured
    EligibilityResult to an LLM and asks it to rephrase into warmer
    prose. Never asked to decide anything — the prompt embeds the
    already-computed status and per-condition results as ground
    truth and explicitly forbids inventing or changing them. This is
    the "grounded generation" principle from the project plan: the
    LLM explains a fact, it doesn't create one.

The LLM generator takes an `llm_call: Callable[[str], str]` rather
than importing a specific SDK directly. That's what makes it testable
offline too — tests inject a fake callable and assert on the prompt
that was built and how the response was handled, with zero network
calls. `anthropic_llm_call()` below is the real callable you'd use to
actually hit an API, built only when you call that factory function
(so importing this module never requires an API key to exist).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

from rule_engine.engine import ConditionStatus, EligibilityResult, EligibilityStatus

LLMCallFn = Callable[[str], str]


class ExplanationGenerator(ABC):
    @abstractmethod
    def generate(self, result: EligibilityResult) -> str:
        raise NotImplementedError

    def generate_all(self, results: List[EligibilityResult]) -> Dict[str, str]:
        return {r.scheme_id: self.generate(r) for r in results}


# --- template-based (default) --------------------------------------------

class TemplateExplanationGenerator(ExplanationGenerator):
    def generate(self, result: EligibilityResult) -> str:
        passed = [c.message for c in result.conditions if c.status == ConditionStatus.PASS]
        failed = [c.message for c in result.conditions if c.status == ConditionStatus.FAIL]
        missing = [c.message for c in result.conditions if c.status == ConditionStatus.MISSING_INFO]
        review = [c.message for c in result.conditions if c.status == ConditionStatus.NEEDS_REVIEW]

        if result.status == EligibilityStatus.ELIGIBLE:
            reasons = " ".join(passed) or "All eligibility conditions for this scheme are satisfied."
            return f"You are ELIGIBLE for {result.scheme_name}. {reasons}"

        if result.status == EligibilityStatus.NOT_ELIGIBLE:
            reasons = " ".join(failed)
            return f"You are NOT ELIGIBLE for {result.scheme_name}. {reasons}"

        if result.status == EligibilityStatus.PARTIALLY_ELIGIBLE:
            reasons = " ".join(missing)
            return (
                f"We can't yet confirm your eligibility for {result.scheme_name} — "
                f"a bit more information is needed. {reasons}"
            )

        if result.status == EligibilityStatus.NEEDS_MANUAL_REVIEW:
            satisfied_note = f"The conditions we can check automatically are satisfied. " if passed else ""
            conditions_list = "; ".join(review)
            return (
                f"{result.scheme_name} looks like a possible match. {satisfied_note}"
                f"However, it also requires manual verification of: {conditions_list}. "
                f"Please confirm these directly with the department or via the application link."
            )

        return f"Could not determine status for {result.scheme_name}."  # defensive fallback


# --- LLM-based (optional, grounded) --------------------------------------

_PROMPT_TEMPLATE = """You are explaining a government scheme eligibility decision that has ALREADY been made by a separate, deterministic rule engine. You are not deciding anything — only rephrasing the decision below into clear, warm, plain language for someone who may not know government scheme terminology.

Scheme: {scheme_name}
Decision: {status}

Conditions checked:
{conditions_block}

Write a short explanation (2-4 sentences) of this decision for the applicant.
Rules:
- Do NOT invent, change, or guess at any criteria not listed above.
- If the decision is PARTIALLY_ELIGIBLE, clearly state what information is still needed.
- If the decision is NEEDS_MANUAL_REVIEW, plainly list what needs manual verification.
- Use the specific numbers/values given above where relevant.
- Do not mention "rule engine" or that you were given structured data — just explain naturally.
"""


def _format_conditions_block(result: EligibilityResult) -> str:
    lines = [f"- [{c.status.value}] {c.field}: {c.message}" for c in result.conditions]
    return "\n".join(lines) if lines else "(no specific conditions restrict this scheme)"


def build_prompt(result: EligibilityResult) -> str:
    return _PROMPT_TEMPLATE.format(
        scheme_name=result.scheme_name,
        status=result.status.value,
        conditions_block=_format_conditions_block(result),
    )


class LLMExplanationGenerator(ExplanationGenerator):
    """
    Dependency-injected on purpose: `llm_call` is any
    `str -> str` function. Swap in a real API client for production,
    or a fake/recording function in tests — this class never imports
    a specific SDK itself, so it never requires network or API keys
    to be importable or unit-testable.
    """

    def __init__(self, llm_call: LLMCallFn, fallback: Optional[ExplanationGenerator] = None):
        self.llm_call = llm_call
        self.fallback = fallback or TemplateExplanationGenerator()

    def generate(self, result: EligibilityResult) -> str:
        prompt = build_prompt(result)
        try:
            text = self.llm_call(prompt)
            if not text or not text.strip():
                raise ValueError("empty LLM response")
            return text.strip()
        except Exception:
            # Never let an LLM/network hiccup break the demo — a
            # template explanation is always available as a fallback.
            return self.fallback.generate(result)


def anthropic_llm_call(model: str = "claude-sonnet-4-6", max_tokens: int = 300) -> LLMCallFn:
    """
    Real-world factory: returns a callable that actually hits the
    Anthropic API. Only imports the SDK and reads the API key when
    THIS function is called — never at module import time — so the
    rest of this file (and every offline test) works with zero setup.

    Usage:
        generator = LLMExplanationGenerator(anthropic_llm_call())
    Requires: pip install anthropic, and ANTHROPIC_API_KEY set in the
    environment.
    """
    try:
        import anthropic
    except ImportError as e:
        raise ImportError(
            "The 'anthropic' package is required for LLM-based explanations. "
            "Install with: pip install anthropic"
        ) from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it, or use TemplateExplanationGenerator instead."
        )

    client = anthropic.Anthropic(api_key=api_key)

    def _call(prompt: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    return _call
