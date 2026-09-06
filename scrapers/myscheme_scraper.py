"""
Scraper for a "standard" government scheme detail page: a title, a
description block, a bulleted eligibility list, benefits, and a
documents list.

IMPORTANT CAVEAT (write this in your report — examiners will ask):
Many real portals, including myscheme.gov.in, render content
client-side via JavaScript (React/Next.js). A plain `requests.get()`
will often return an near-empty HTML shell with no scheme data in it,
because the content is injected by JS after page load. For those
sites you have two options:
  1. Use their underlying JSON API directly, if you can find it via
     browser devtools (Network tab -> XHR/Fetch) — much more robust
     and faster than scraping rendered HTML.
  2. Use a headless browser (Selenium / Playwright) to render the page
     first, then hand the rendered HTML to a parser like this one.
This module assumes you already have server-rendered or pre-fetched
HTML (e.g. via Playwright, or a state site that IS server-rendered).
The CSS selectors below match the fixture in
tests/fixtures/sample_scheme_page.html — inspect your real target
page and adjust selectors accordingly; they will differ per source.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from schema import EligibilityCriteria, Gender, Scheme, SchemeCategory
from scrapers.base_scraper import BaseSchemeScraper, ScraperError

# --- naive regex helpers for pulling numbers out of eligibility prose ---
# These are intentionally simple. For Module 1 the recommendation is
# manual annotation of your first 15-20 schemes (see project plan) —
# treat this as a starting point / time-saver, not a black box you
# trust blindly. Always eyeball the output.

_AGE_MIN_RE = re.compile(r"aged?\s+(\d{1,3})\s+years?\s+(?:or\s+above|and\s+above|or\s+more)", re.I)
_INCOME_MAX_RE = re.compile(r"income.{0,20}?not\s+exceed.{0,10}?Rs\.?\s*([\d,]+)", re.I)


def _parse_money(s: str) -> int:
    return int(s.replace(",", ""))


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


class MySchemeStyleScraper(BaseSchemeScraper):
    source_name = "myscheme_style"

    def parse_html(self, html: str, source_url: str) -> Scheme:
        soup = BeautifulSoup(html, "html.parser")

        try:
            title = soup.select_one(".scheme-title").get_text(strip=True)
            department = soup.select_one(".scheme-department").get_text(strip=True)
            category_raw = soup.select_one(".scheme-category").get_text(strip=True).lower()
            description = _normalize_whitespace(
                soup.select_one(".scheme-description p").get_text()
            )
            eligibility_items = [
                li.get_text(strip=True) for li in soup.select(".eligibility li")
            ]
            benefits = soup.select_one(".benefits p").get_text(strip=True)
            documents = [li.get_text(strip=True) for li in soup.select(".documents li")]
        except AttributeError as e:
            # .get_text() on a None selector result raises AttributeError —
            # translate to ScraperError so the pipeline can log-and-skip.
            raise ScraperError(f"Expected element missing in {source_url}: {e}") from e

        if not eligibility_items:
            raise ScraperError(f"No eligibility items found at {source_url}")

        eligibility_text = " ".join(eligibility_items)
        eligibility = self._extract_eligibility(eligibility_text)

        apply_link_tag = soup.select_one(".apply-link")
        application_link = apply_link_tag["href"] if apply_link_tag else None

        category = self._map_category(category_raw)

        scheme_id = self._slugify(title)

        return Scheme(
            scheme_id=scheme_id,
            name=title,
            description=description,
            department=department,
            category=category,
            eligibility=eligibility,
            benefits=benefits,
            documents_required=documents,
            application_link=application_link,
            source_url=source_url,
            last_verified=self.today(),
            verified_by="llm_assisted",  # regex-assisted here; mark
            # "manual" once a human has reviewed and corrected the output
        )

    @staticmethod
    def _extract_eligibility(text: str) -> EligibilityCriteria:
        age_min = None
        income_max = None
        state = None
        gender = None

        m = _AGE_MIN_RE.search(text)
        if m:
            age_min = int(m.group(1))

        m = _INCOME_MAX_RE.search(text)
        if m:
            income_max = _parse_money(m.group(1))

        if "gujarat" in text.lower():
            state = ["gujarat"]

        if "male and female" in text.lower() or "both male" in text.lower():
            gender = Gender.ANY

        return EligibilityCriteria(
            age_min=age_min,
            income_max=income_max,
            state=state,
            gender=gender,
        )

    @staticmethod
    def _map_category(raw: str) -> SchemeCategory:
        mapping = {
            "pension": SchemeCategory.PENSION,
            "agriculture": SchemeCategory.AGRICULTURE,
            "health": SchemeCategory.HEALTHCARE,
            "healthcare": SchemeCategory.HEALTHCARE,
            "education": SchemeCategory.EDUCATION,
            "housing": SchemeCategory.HOUSING,
            "employment": SchemeCategory.EMPLOYMENT,
        }
        return mapping.get(raw, SchemeCategory.OTHER)

    @staticmethod
    def _slugify(title: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
