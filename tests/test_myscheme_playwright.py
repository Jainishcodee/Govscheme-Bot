"""Offline tests for the Playwright scraper's parser and batch controls."""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema import EligibilityCriteria, Scheme, SchemeCategory  # noqa: E402
from scrapers.myscheme_playwright import MySchemePlaywrightScraper  # noqa: E402


NOISY_PAGE = """
<html><body>
<header>myScheme navigation, search bar, menus</header>
<nav>Home Search Schemes Login</nav>
<main>
  <h1>Women Entrepreneurship Support</h1>
  <p>Ministry: Ministry of Skill Development</p>
  <section><h2>About</h2><p>A grant for women starting eligible businesses.</p></section>
  <section><h2>Benefits</h2><ul><li>Grant support up to Rs. 2 lakh.</li></ul></section>
  <section><h2>Eligibility</h2><ul><li>Women aged 18 years or above.</li><li>Resident of Gujarat.</li></ul></section>
  <section><h2>Documents Required</h2><ul><li>Aadhaar card</li></ul></section>
  <section><h2>How to Apply</h2><ol><li>Apply through the official portal.</li></ol></section>
  <a href="https://official.example/apply">Official application</a>
</main>
<footer>Footer links and unrelated content</footer>
</body></html>
"""


def test_description_excludes_site_chrome_and_maps_sections():
    scheme = MySchemePlaywrightScraper().parse_html(
        NOISY_PAGE, "https://www.myscheme.gov.in/schemes/women-entrepreneurship"
    )

    assert scheme.description == "A grant for women starting eligible businesses."
    assert "navigation" not in scheme.description.lower()
    assert "search bar" not in scheme.description.lower()
    assert scheme.benefits == "Grant support up to Rs. 2 lakh."
    assert scheme.documents_required == ["Aadhaar card"]
    assert scheme.eligibility.age_min == 18
    assert scheme.eligibility.gender == "female"
    assert scheme.eligibility.state == ["gujarat"]
    assert str(scheme.application_link) == "https://official.example/apply"
    assert any("Application process" in item for item in scheme.eligibility.additional_conditions)


class FakeBatchScraper(MySchemePlaywrightScraper):
    def scrape_url(self, url: str) -> Scheme:
        return Scheme(
            scheme_id=url.rstrip("/").rsplit("/", 1)[-1],
            name="Test scheme",
            description="Test description",
            department="Test ministry",
            category=SchemeCategory.OTHER,
            eligibility=EligibilityCriteria(),
            benefits="Test benefit",
            source_url=url,
            last_verified=date.today(),
        )


def test_batch_limits_and_deduplicates_for_1_5_and_20():
    scraper = FakeBatchScraper(delay_seconds=0)
    urls = [f"https://www.myscheme.gov.in/schemes/test-{index}" for index in range(20)]
    urls.insert(1, urls[0])

    for limit, expected in ((1, 1), (5, 5), (20, 20)):
        report = scraper.scrape_urls(urls, limit=limit)
        assert len(report.discovered_urls) == expected
        assert report.successful_count == expected
        assert report.failed_count == 0


if __name__ == "__main__":
    test_description_excludes_site_chrome_and_maps_sections()
    test_batch_limits_and_deduplicates_for_1_5_and_20()
    print("ALL PLAYWRIGHT SCRAPER OFFLINE TESTS PASSED")
