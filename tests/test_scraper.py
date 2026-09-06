"""
Run with: python3 tests/test_scraper.py
(from the govscheme_bot/ root — no network access needed, uses the
local fixture in tests/fixtures/)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrapers.myscheme_scraper import MySchemeStyleScraper  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_scheme_page.html")


def test_parses_fixture_into_valid_scheme():
    scraper = MySchemeStyleScraper()
    scheme = scraper.scrape_from_file(
        FIXTURE, source_url="https://example.gov.in/vay-vandana"
    )

    assert scheme.name == "Vay Vandana Pension Yojana"
    assert scheme.eligibility.age_min == 60
    assert scheme.eligibility.income_max == 150_000
    assert scheme.eligibility.state == ["gujarat"]
    assert len(scheme.documents_required) == 4
    print("PASS —", scheme.model_dump_json(indent=2))


if __name__ == "__main__":
    test_parses_fixture_into_valid_scheme()
