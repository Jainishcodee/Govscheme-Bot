"""
Typo-tolerant vocabulary matching: "tacher" -> "teacher", "gujrat" ->
"gujarat", "maharastra" -> "maharashtra".

Why this exists
---------------
Module 4's extractor matches categorical fields with a spaCy
PhraseMatcher, which is exact by design — it compares token
*sequences*, so a single typo ("I'm a tacher") silently extracts
nothing and the rule engine falls back to MISSING_INFO instead of
answering the question the user actually asked. The same holds for
retrieval: a typo'd query shares no word-level TF-IDF terms with the
corpus, so the search quietly ranks badly instead of erroring.

Both failure modes are silent, which is worse than an error. This
module fixes them with a deterministic fuzzy corrector — same
philosophy as the rest of the project: fully explainable, no model
download, no LLM, and every correction is reported back to the caller
so the UI can show "I read that as ...".

Placement: root-level like `schema.py`, because two different packages
need it (`nlp_extraction/` for profile extraction and `retrieval/` for
query rewriting) and neither should import the other. The domain
vocabulary still lives in `nlp_extraction/lookups.py`; this module
only borrows it.

How a correction is accepted (deliberately conservative)
--------------------------------------------------------
A token is only rewritten when ALL of these hold:

  1. it is not already an exact vocabulary word,
  2. it is at least `min_token_length` (4) characters — short tokens
     are exact-match only, which is what stops "make" -> "male" and
     keeps "sc"/"st"/"obc"/"bpl" behaving as exact keys,
  3. its Damerau-Levenshtein distance to a candidate is within
     `short_max_distance` (1) for short tokens and `max_distance` (2)
     for longer ones — adjacent-transposition aware, because typos
     like "widwo" are overwhelmingly swaps, not substitutions,
  4. the similarity ratio is >= `similarity_threshold` (0.8) — this is
     the guard that rejects "teach" -> "teacher" (ratio 0.71) while
     accepting "tacher" -> "teacher" (0.92),
  5. exactly one candidate wins — ties fall back to leaving the token
     alone rather than guessing.

If a word reads as correct English but isn't in our vocabulary, rule 4
usually saves it (there is no general English dictionary here on
purpose — see limitations below).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from nlp_extraction import lookups

# Latin-alphabet runs only; punctuation, digits and hyphens are left
# untouched so they pass through the reassembled text unchanged.
_TOKEN_RE = re.compile(r"[A-Za-z]+")


# --- distance -----------------------------------------------------------

def damerau_levenshtein(a: str, b: str) -> int:
    """
    Optimal string alignment distance (restricted Damerau-Levenshtein):
    insertions, deletions, substitutions and *adjacent* transpositions,
    each costing 1. Plain Levenshtein charges 2 for a transposition,
    which would push common typos past our short-token limit.
    """
    if a == b:
        return 0
    prev_prev: List[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(prev[j] + 1, current[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                value = min(value, prev_prev[j - 2] + 1)
            current.append(value)
        prev_prev, prev = prev, current
    return prev[-1]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# --- vocabulary builders -------------------------------------------------

def vocabulary_from_texts(texts: Iterable[object]) -> Set[str]:
    """Flatten free text into the set of lowercase words it contains."""
    vocabulary: Set[str] = set()
    for text in texts:
        vocabulary.update(token.lower() for token in _TOKEN_RE.findall(str(text)))
    return vocabulary


def domain_vocabulary() -> Set[str]:
    """
    Every word in Module 4's hand-curated vocabulary — surface phrases
    *and* their normalized values, so both sides of the mapping are
    searchable ("landless_laborer" contributes "landless" and
    "laborer").
    """
    phrases: List[str] = list(lookups.INDIAN_STATES)
    phrases += list(lookups.DISABILITY_TERMS)
    phrases += list(lookups.BPL_TERMS)
    for term_map in (
        lookups.OCCUPATION_TERMS,
        lookups.CASTE_TERMS,
        lookups.MARITAL_TERMS,
        lookups.GENDER_TERMS,
    ):
        phrases += list(term_map.keys())
        phrases += list(term_map.values())
    return vocabulary_from_texts(phrases)


# --- the corrector --------------------------------------------------------

class TokenCorrector:
    """
    Corrects single tokens against a fixed vocabulary.

    Dependency-injected vocabulary: the extractor builds one from
    `lookups` (states, occupations, caste terms...), the retriever
    builds one from the scheme corpus it already owns. Neither needs to
    import the other, and tests can hand in a tiny vocabulary to pin
    down exactly the behaviour they care about.
    """

    def __init__(
        self,
        vocabulary: Iterable[str],
        *,
        min_token_length: int = 4,
        short_max_length: int = 5,
        short_max_distance: int = 1,
        max_distance: int = 2,
        similarity_threshold: float = 0.8,
    ):
        self._vocabulary: Set[str] = {
            word.lower() for word in vocabulary_from_texts(vocabulary)
        }
        self.min_token_length = min_token_length
        self.short_max_length = short_max_length
        self.short_max_distance = short_max_distance
        self.max_distance = max_distance
        self.similarity_threshold = similarity_threshold
        self._cache: Dict[str, str] = {}

    @property
    def vocabulary(self) -> Set[str]:
        return set(self._vocabulary)

    def correct_word(self, token: str) -> str:
        """Return the corrected token, or the token unchanged."""
        cached = self._cache.get(token)
        if cached is not None:
            return cached

        result = self._correct_word(token)
        self._cache[token] = result
        return result

    def _correct_word(self, token: str) -> str:
        lowered = token.lower()
        if len(lowered) < self.min_token_length or lowered in self._vocabulary:
            return token

        limit = (
            self.short_max_distance
            if len(lowered) <= self.short_max_length
            else self.max_distance
        )

        best_word: Optional[str] = None
        best_distance = 0
        best_ratio = 0.0
        ambiguous = False

        for candidate in self._vocabulary:
            if abs(len(candidate) - len(lowered)) > limit:
                continue
            distance = damerau_levenshtein(lowered, candidate)
            if distance == 0 or distance > limit:
                continue
            ratio = _similarity(lowered, candidate)
            if ratio < self.similarity_threshold:
                continue

            if best_word is None or distance < best_distance or (
                distance == best_distance and ratio > best_ratio
            ):
                best_word, best_distance, best_ratio = candidate, distance, ratio
                ambiguous = False
            elif distance == best_distance and candidate != best_word:
                # Two candidates equally close and equally plausible —
                # leave it alone rather than guess which was meant.
                ambiguous = ambiguous or abs(ratio - best_ratio) < 1e-9

        if best_word is None or ambiguous:
            return token
        return _match_case(token, best_word)

    def correct_text(self, text: str) -> Tuple[str, List[Tuple[str, str]]]:
        """
        Rewrite the text with typos fixed, and report each distinct
        `(original, corrected)` pair so the caller can surface it.
        Punctuation, digits and spacing are preserved exactly.
        """
        parts: List[str] = []
        corrections: List[Tuple[str, str]] = []
        seen: Set[Tuple[str, str]] = set()
        cursor = 0

        for match in _TOKEN_RE.finditer(text):
            token = match.group(0)
            fixed = self.correct_word(token)
            parts.append(text[cursor:match.start()])
            parts.append(fixed)
            cursor = match.end()

            if fixed != token:
                pair = (token, fixed)
                if pair not in seen:
                    seen.add(pair)
                    corrections.append(pair)

        parts.append(text[cursor:])
        return "".join(parts), corrections


def _match_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


# --- module-level convenience ---------------------------------------------

_DOMAIN_CORRECTOR: Optional[TokenCorrector] = None


def domain_corrector() -> TokenCorrector:
    """Shared corrector over Module 4's vocabulary (built once)."""
    global _DOMAIN_CORRECTOR
    if _DOMAIN_CORRECTOR is None:
        _DOMAIN_CORRECTOR = TokenCorrector(domain_vocabulary())
    return _DOMAIN_CORRECTOR


def correct(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Correct typos against the domain vocabulary."""
    return domain_corrector().correct_text(text)
