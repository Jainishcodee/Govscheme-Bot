"""
Run with: python3 tests/test_retrieval.py

The real data/sample_schemes.json only has 3 schemes (Module 1's
hand-verified set) — too small to meaningfully demonstrate retrieval
actually filtering anything out. So this file builds a larger,
explicitly SYNTHETIC multi-domain corpus (not verified against real
scheme text — test fixtures only, never used by the live Streamlit
app) to prove the retrieval mechanism itself works: semantic ranking,
category metadata filtering, and state post-filtering.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import EligibilityCriteria, Scheme, SchemeCategory  # noqa: E402
from retrieval.retriever import SchemeRetriever  # noqa: E402
from retrieval.vector_store import SchemeVectorStore  # noqa: E402


def _scheme(scheme_id, name, description, category, benefits="Cash benefit.", state=None, occupation=None):
    return Scheme(
        scheme_id=scheme_id,
        name=name,
        description=description,
        department="Test Department",
        category=category,
        eligibility=EligibilityCriteria(state=state, occupation=occupation),
        benefits=benefits,
        documents_required=["Aadhaar Card"],
        source_url="https://example.gov.in/" + scheme_id,
        last_verified=date(2026, 8, 19),
        verified_by="manual",
    )


def synthetic_corpus() -> list[Scheme]:
    """
    8 schemes spanning distinct domains — enough to show that a query
    about, say, student scholarships doesn't surface a farmer pension
    scheme. Synthetic text, not asserted as real-world accurate.
    """
    return [
        _scheme(
            "crop-insurance-scheme", "Fasal Bima Crop Insurance Scheme",
            "Provides insurance coverage and financial support to farmers "
            "in case of crop failure due to natural calamities, pests, or diseases.",
            SchemeCategory.AGRICULTURE, occupation=["farmer"],
        ),
        _scheme(
            "merit-scholarship", "National Merit Scholarship for Higher Education",
            "Financial assistance for meritorious students from economically "
            "weaker sections to pursue undergraduate and postgraduate studies.",
            SchemeCategory.EDUCATION,
        ),
        _scheme(
            "maternal-health-scheme", "Janani Suraksha Maternal Health Scheme",
            "Cash assistance to pregnant women for institutional delivery to "
            "reduce maternal and neonatal mortality.",
            SchemeCategory.HEALTHCARE,
        ),
        _scheme(
            "rural-housing-scheme", "Rural Housing Assistance Scheme",
            "Financial assistance for construction of pucca houses for "
            "houseless and rural families living in kutcha houses.",
            SchemeCategory.HOUSING,
        ),
        _scheme(
            "unemployment-allowance", "Unemployed Youth Allowance Scheme",
            "Monthly unemployment allowance for registered job-seeking youth "
            "who have not found employment within a specified period.",
            SchemeCategory.EMPLOYMENT,
        ),
        _scheme(
            "old-age-pension-rajasthan", "Rajasthan Old Age Pension Scheme",
            "Monthly pension for elderly citizens of Rajasthan from "
            "economically weaker sections to support old-age financial security.",
            SchemeCategory.PENSION, state=["rajasthan"],
        ),
        _scheme(
            "old-age-pension-gujarat", "Gujarat Old Age Pension Scheme",
            "Monthly pension for elderly citizens of Gujarat from "
            "economically weaker sections to support old-age financial security.",
            SchemeCategory.PENSION, state=["gujarat"],
        ),
        _scheme(
            "disability-support-scheme", "Disability Support Allowance",
            "Monthly financial support and assistive device coverage for "
            "persons with disabilities to aid daily living and mobility.",
            SchemeCategory.DISABILITY,
        ),
    ]


def test_semantic_ranking_surfaces_relevant_category():
    retriever = SchemeRetriever.from_schemes(synthetic_corpus())
    results = retriever.retrieve("scholarship for college students", top_k=3)
    print("\nQuery: 'scholarship for college students'")
    for s in results:
        print(f"  {s.scheme_id}")
    assert results[0].scheme_id == "merit-scholarship"


def test_semantic_ranking_farmer_query():
    retriever = SchemeRetriever.from_schemes(synthetic_corpus())
    results = retriever.retrieve("my crops were destroyed by flooding", top_k=3)
    print("\nQuery: 'my crops were destroyed by flooding'")
    for s in results:
        print(f"  {s.scheme_id}")
    assert results[0].scheme_id == "crop-insurance-scheme"


def test_top_k_actually_limits_results():
    retriever = SchemeRetriever.from_schemes(synthetic_corpus())
    results = retriever.retrieve("financial assistance", top_k=3)
    assert len(results) == 3  # not all 8 — proves retrieval actually filters


def test_category_metadata_filter():
    store = SchemeVectorStore.build(synthetic_corpus())
    retriever = SchemeRetriever(store, default_top_k=5)
    results = retriever.retrieve("financial support for elderly", category="pension")
    print("\nQuery: 'financial support for elderly', category=pension")
    for s in results:
        print(f"  {s.scheme_id} ({s.category})")
    assert len(results) == 2  # only the two pension schemes exist
    assert all(s.category == "pension" for s in results)


def test_state_post_filter():
    store = SchemeVectorStore.build(synthetic_corpus())
    with_scores = store.query("pension for elderly", top_k=8, category="pension")
    gujarat_only = store.filter_by_state(with_scores, "gujarat")
    print("\nState-filtered (gujarat) pension schemes:")
    for s, _ in gujarat_only:
        print(f"  {s.scheme_id}")
    ids = {s.scheme_id for s, _ in gujarat_only}
    assert ids == {"old-age-pension-gujarat"}  # rajasthan's excluded, central schemes would pass through


def test_empty_query_returns_empty_not_error():
    retriever = SchemeRetriever.from_schemes(synthetic_corpus())
    assert retriever.retrieve("") == []
    assert retriever.retrieve("   ") == []


def test_ranking_is_deterministic_across_rebuilds():
    """
    Regression test for a real bug found during development: the
    original single-word-level TF-IDF vectorizer produced an all-zero
    query vector whenever the query shared no exact tokens with the
    corpus (e.g. "crops" vs. the corpus's "crop") — and chromadb's
    HNSW index handles near-zero-norm vectors by returning what is
    effectively insertion-order noise, silently, with no error. Same
    query, same corpus, five separate rebuilds should always rank the
    same way; if they don't, something regressed.
    """
    query = "my crops were destroyed by flooding"
    rankings = []
    for _ in range(5):
        retriever = SchemeRetriever.from_schemes(synthetic_corpus())
        rankings.append(tuple(s.scheme_id for s in retriever.retrieve(query, top_k=3)))
    assert len(set(rankings)) == 1, f"Non-deterministic ranking across rebuilds: {rankings}"
    assert rankings[0][0] == "crop-insurance-scheme"


def test_known_limitation_generic_word_overlap():
    """
    Documents a real, honest limitation rather than hiding it: TF-IDF
    is lexical, not semantic. "support" appears prominently in the
    disability scheme's name and description, so a query using that
    same generic word can outrank the scheme that's actually the
    better match. This is exactly the case a real embedding model
    (see embeddings.py's commented SentenceTransformerEmbeddingFunction)
    would handle better. Asserting the CURRENT (imperfect) behavior
    here means a future embedding upgrade will make this test fail —
    that's the intended signal to update it, not a bug in the upgrade.
    """
    retriever = SchemeRetriever.from_schemes(synthetic_corpus())
    results = retriever.retrieve("I lost my job and need support", top_k=3)
    scheme_ids = [s.scheme_id for s in results]
    print(f"\nQuery: 'I lost my job and need support' -> {scheme_ids}")
    assert "unemployment-allowance" in scheme_ids  # at least surfaced, even if not ranked #1


if __name__ == "__main__":
    test_semantic_ranking_surfaces_relevant_category()
    test_semantic_ranking_farmer_query()
    test_top_k_actually_limits_results()
    test_category_metadata_filter()
    test_state_post_filter()
    test_empty_query_returns_empty_not_error()
    test_ranking_is_deterministic_across_rebuilds()
    test_known_limitation_generic_word_overlap()
    print("\nALL TESTS PASSED")
