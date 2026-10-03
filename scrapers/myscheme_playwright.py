"""Playwright scraper for the JavaScript-rendered myScheme portal.

This module uses normal browser navigation only. It does not solve or bypass
CAPTCHAs, authentication, anti-bot checks, or rate limits. A blocked page is
recorded as a failure so it can be retried later by a human-approved run.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from schema import CasteCategory, EligibilityCriteria, Gender, Scheme, SchemeCategory
from scrapers.base_scraper import ScraperError
from scrapers.myscheme_scraper import MySchemeStyleScraper

BASE_URL = "https://www.myscheme.gov.in/"
DEFAULT_LISTING_URL = f"{BASE_URL}dashboard"
SCHEME_PATH_RE = re.compile(r"/(?:schemes?|scheme)/[^/?#]+", re.I)
BLOCKED_TEXT_RE = re.compile(
    r"captcha|verify you are human|access denied|cloudflare|unusual traffic",
    re.I,
)
SECTION_NAMES = {
    "about": "about",
    "overview": "about",
    "description": "about",
    "benefit": "benefits",
    "benefits": "benefits",
    "eligibility": "eligibility",
    "who can apply": "eligibility",
    "documents required": "documents",
    "documents": "documents",
    "how to apply": "application",
    "application process": "application",
    "application procedure": "application",
    "objective": "objectives",
    "objectives": "objectives",
    "target beneficiaries": "beneficiaries",
    "beneficiaries": "beneficiaries",
}


@dataclass
class ScrapeReport:
    discovered_urls: list[str] = field(default_factory=list)
    schemes: list[Scheme] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def successful_count(self) -> int:
        return len(self.schemes)

    @property
    def failed_count(self) -> int:
        return len(self.failures)


class MySchemePlaywrightScraper(MySchemeStyleScraper):
    """Discover and parse myScheme pages using a rendered browser DOM."""

    source_name = "myscheme.gov.in"

    def __init__(self, timeout_ms: int = 30_000, retries: int = 2, delay_seconds: float = 1.0):
        self.timeout_ms = timeout_ms
        self.retries = max(0, retries)
        self.delay_seconds = max(0.0, delay_seconds)

    @staticmethod
    def _normalise_url(url: str, base_url: str = BASE_URL) -> str:
        absolute = urljoin(base_url, url.split("#", 1)[0])
        parsed = urlparse(absolute)
        return parsed._replace(query=parsed.query, fragment="").geturl().rstrip("/") + "/"

    @classmethod
    def _is_scheme_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and parsed.netloc.endswith("myscheme.gov.in") and bool(SCHEME_PATH_RE.search(parsed.path))

    @staticmethod
    def _assert_not_blocked(text: str, url: str) -> None:
        if BLOCKED_TEXT_RE.search(text):
            raise ScraperError(
                f"Possible CAPTCHA or anti-bot page at {url}; no bypass was attempted"
            )

    def _new_browser_page(self, playwright):
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="GovSchemeEligibilityBot/0.1 (student project; respectful rate limits)"
        )
        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return browser, context, page

    def discover_scheme_urls(
        self,
        listing_url: str = BASE_URL,
        max_pages: int = 100,
    ) -> list[str]:
        """Collect unique scheme detail URLs from listing/load-more pages."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ScraperError(
                "Playwright is required. Install requirements.txt and run "
                "'playwright install chromium'."
            ) from exc

        discovered: set[str] = set()
        visited_signatures: set[str] = set()
        current_url = listing_url
        try:
            with sync_playwright() as playwright:
                browser, context, page = self._new_browser_page(playwright)
                try:
                    for _ in range(max_pages):
                        page.goto(current_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
                        body_text = page.locator("body").inner_text(timeout=self.timeout_ms)
                        self._assert_not_blocked(body_text, current_url)
                        signature = f"{current_url}|{len(body_text)}|{body_text[-300:]}"
                        if signature in visited_signatures:
                            break
                        visited_signatures.add(signature)

                        hrefs = self._page_hrefs(page)
                        before = len(discovered)
                        self._add_scheme_hrefs(discovered, hrefs, current_url)

                        if not discovered:
                            self._submit_search(page, "scheme")
                            hrefs = self._page_hrefs(page)
                            self._add_scheme_hrefs(discovered, hrefs, current_url)

                        next_url = self._find_next_url(page, current_url)
                        if next_url and next_url != current_url and len(discovered) > before:
                            current_url = next_url
                            continue

                        clicked = self._click_load_more(page)
                        if clicked:
                            page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
                            body_text = page.locator("body").inner_text(timeout=self.timeout_ms)
                            self._assert_not_blocked(body_text, current_url)
                            self._add_scheme_hrefs(discovered, self._page_hrefs(page), current_url)
                            if len(discovered) > before:
                                continue
                        break
                finally:
                    context.close()
                    browser.close()
        except Exception as exc:
            if isinstance(exc, ScraperError):
                raise
            raise ScraperError(f"Failed to discover schemes from {listing_url}: {exc}") from exc
        return sorted(discovered)

    def _find_next_url(self, page, current_url: str) -> str | None:
        selectors = [
            "a[rel='next'][href]",
            "a:has-text('Next')[href]",
            "button:has-text('Next')",
        ]
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() == 0 or not locator.is_visible():
                continue
            href = locator.get_attribute("href")
            if href:
                return self._normalise_url(href, current_url)
        return None

    @staticmethod
    def _page_hrefs(page) -> list[str]:
        return page.locator("a[href], [data-href]").evaluate_all(
            "els => els.map(e => e.href || e.dataset.href).filter(Boolean)"
        )

    @classmethod
    def _add_scheme_hrefs(cls, target: set[str], hrefs: Iterable[str], base_url: str) -> None:
        for href in hrefs:
            normalised = cls._normalise_url(href, base_url)
            if cls._is_scheme_url(normalised):
                target.add(normalised)

    @staticmethod
    def _submit_search(page, query: str) -> None:
        search_box = page.locator("input[type='search'], input[placeholder*='scheme' i], input[type='text']").first
        if search_box.count() == 0 or not search_box.is_visible():
            return
        search_box.fill(query)
        search_box.press("Enter")
        page.wait_for_load_state("networkidle", timeout=30_000)

    @staticmethod
    def _click_load_more(page) -> bool:
        for label in ("load more", "show more", "more schemes"):
            locator = page.get_by_text(re.compile(label, re.I)).last
            if locator.count() and locator.is_visible() and locator.is_enabled():
                locator.click()
                return True
        return False

    def scrape_url(self, url: str) -> Scheme:
        """Render one scheme page and parse only its scheme content sections."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ScraperError("Playwright is required for rendered scraping") from exc

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with sync_playwright() as playwright:
                    browser, context, page = self._new_browser_page(playwright)
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
                        html = page.content()
                        self._assert_not_blocked(page.locator("body").inner_text(), url)
                    finally:
                        context.close()
                        browser.close()
                return self.parse_html(html, source_url=url)
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
        raise ScraperError(f"Failed to scrape {url}: {last_error}") from last_error

    def scrape_urls(self, urls: Iterable[str], limit: int | None = None) -> ScrapeReport:
        """Scrape URLs independently; one failure never stops the batch."""
        unique_urls = list(dict.fromkeys(self._normalise_url(url) for url in urls))
        if limit is not None:
            unique_urls = unique_urls[:limit]
        report = ScrapeReport(discovered_urls=unique_urls)
        for index, url in enumerate(unique_urls):
            try:
                scheme = self.scrape_url(url)
                if not any(str(existing.source_url) == str(scheme.source_url) for existing in report.schemes):
                    report.schemes.append(scheme)
            except ScraperError as exc:
                report.failures[url] = str(exc)
            if index + 1 < len(unique_urls):
                time.sleep(self.delay_seconds)
        return report

    def scrape_listing(self, listing_url: str = DEFAULT_LISTING_URL, limit: int | None = None) -> ScrapeReport:
        urls = self.discover_scheme_urls(listing_url)
        return self.scrape_urls(urls, limit=limit)

    @staticmethod
    def write_report(report: ScrapeReport, output_path: str, failures_path: str) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps([scheme.model_dump(mode="json") for scheme in report.schemes], indent=2),
            encoding="utf-8",
        )
        Path(failures_path).write_text(
            json.dumps(report.failures, indent=2), encoding="utf-8"
        )

    def parse_html(self, html: str, source_url: str) -> Scheme:
        """Parse section-labeled scheme content while excluding site chrome."""
        soup = BeautifulSoup(html, "html.parser")
        root = self._content_root(soup)
        for element in root.select("header, nav, footer, aside, form, [aria-label*='breadcrumb' i], .breadcrumb, .search, .menu"):
            element.decompose()

        title = self._first_text(root, ["h1", ".scheme-title", "[data-testid*='title' i]"])
        if not title:
            raise ScraperError(f"Scheme title not found at {source_url}")

        sections = self._sections(root)
        description = sections.get("about") or self._first_content_paragraph(root, title)
        if not description:
            raise ScraperError(f"Scheme description section not found at {source_url}")

        benefits = sections.get("benefits", "")
        eligibility_text = sections.get("eligibility", "")
        documents_text = sections.get("documents", "")
        application_text = sections.get("application", "")
        department = self._label_value(root, "ministry") or self._label_value(root, "department") or ""
        ministry = self._label_value(root, "ministry")
        source_scope = self._label_value(root, "central/state") or self._label_value(root, "scheme type")
        application_link = self._application_link(root, source_url)
        category = self._map_category(self._label_value(root, "category") or "")
        eligibility = self._extract_myscheme_eligibility(eligibility_text)
        documents = self._list_values(root, "documents")
        if not documents and documents_text:
            documents = self._split_lines(documents_text)

        additional = []
        for label, value in (
            ("Objectives", sections.get("objectives")),
            ("Target beneficiaries", sections.get("beneficiaries")),
            ("Application process", application_text),
            ("Eligibility details", eligibility_text if not self._has_structured_eligibility(eligibility) else None),
            ("Scope", source_scope),
        ):
            if value:
                additional.append(f"{label}: {value}")

        return Scheme(
            scheme_id=self._slugify(title),
            name=title,
            description=description,
            department=department or ministry or "",
            category=category,
            eligibility=eligibility.model_copy(update={"additional_conditions": additional or None}),
            benefits=benefits,
            documents_required=documents,
            application_link=application_link,
            source_url=source_url,
            last_verified=self.today(),
            verified_by="llm_assisted",
        )

    @staticmethod
    def _content_root(soup: BeautifulSoup):
        candidates = soup.select("main, [role='main'], article, .scheme-details, .scheme-detail")
        return max(candidates, key=lambda node: len(node.select("h1, h2, h3, p, li"))) if candidates else soup

    @staticmethod
    def _first_text(root, selectors: list[str]) -> str:
        for selector in selectors:
            node = root.select_one(selector)
            if node:
                return MySchemePlaywrightScraper._clean(node.get_text(" "))
        return ""

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip(" \n\t:-")

    @classmethod
    def _sections(cls, root) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        headings = root.select("h2, h3, h4")
        for heading in headings:
            key = SECTION_NAMES.get(cls._clean(heading.get_text(" ")).lower())
            if not key:
                continue
            values = []
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h2", "h3", "h4"}:
                    break
                if sibling.name in {"p", "li", "ul", "ol", "div"}:
                    text = cls._clean(sibling.get_text(" "))
                    if text and text not in values:
                        values.append(text)
            if values:
                sections.setdefault(key, []).extend(values)
        return {key: cls._clean(" ".join(dict.fromkeys(values))) for key, values in sections.items()}

    @classmethod
    def _first_content_paragraph(cls, root, title: str) -> str:
        for paragraph in root.select("p"):
            text = cls._clean(paragraph.get_text(" "))
            if text and text.lower() != title.lower() and len(text) > 30:
                return text
        return ""

    @classmethod
    def _label_value(cls, root, label: str) -> str:
        pattern = re.compile(rf"^{re.escape(label)}\s*[:\-]?\s*(.+)$", re.I)
        for node in root.select("dt, dd, p, li, div, span"):
            text = cls._clean(node.get_text(" "))
            match = pattern.match(text)
            if match and match.group(1).strip():
                return cls._clean(match.group(1))
        return ""

    @classmethod
    def _list_values(cls, root, section_key: str) -> list[str]:
        for heading in root.select("h2, h3, h4"):
            if SECTION_NAMES.get(cls._clean(heading.get_text(" ")).lower()) != section_key:
                continue
            values = []
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h2", "h3", "h4"}:
                    break
                values.extend(cls._clean(li.get_text(" ")) for li in sibling.select("li"))
            return list(dict.fromkeys(value for value in values if value))
        return []

    @classmethod
    def _application_link(cls, root, source_url: str) -> str | None:
        for link in root.select("a[href]"):
            text = cls._clean(link.get_text(" ")).lower()
            href = link.get("href", "")
            if href.startswith(("http://", "https://")) and any(term in text for term in ("apply", "official website", "application")):
                return href
        return None

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        return [part.strip(" -•") for part in re.split(r"\s{2,}|\n|(?<=\.) (?=[A-Z])", text) if part.strip(" -•")]

    @staticmethod
    def _has_structured_eligibility(criteria: EligibilityCriteria) -> bool:
        return any(value is not None for value in (
            criteria.age_min, criteria.age_max, criteria.income_min, criteria.income_max,
            criteria.gender, criteria.caste_category, criteria.state, criteria.occupation,
            criteria.disability_status, criteria.bpl_required,
        ))

    @classmethod
    def _extract_myscheme_eligibility(cls, text: str) -> EligibilityCriteria:
        lowered = text.lower()
        age_min = cls._number_after(text, r"(?:minimum age|age|aged)\D{0,20}(\d{1,3})\s*(?:years?|yrs?)")
        age_max = cls._number_after(text, r"(?:maximum age|age limit)\D{0,20}(\d{1,3})\s*(?:years?|yrs?)")
        income_max = cls._money_after(text, r"(?:income|annual income|family income).{0,35}?(?:below|less than|not exceed|up to|maximum)\s*")
        gender = None
        if any(word in lowered for word in ("male and female", "men and women", "all genders", "both genders")):
            gender = Gender.ANY
        elif re.search(r"\b(women|woman|female|girls|girl)\b", lowered):
            gender = Gender.FEMALE
        elif re.search(r"\b(men|man|male|boys|boy)\b", lowered):
            gender = Gender.MALE

        state_terms = re.findall(r"\b(andhra pradesh|arunachal pradesh|assam|bihar|chhattisgarh|delhi|goa|gujarat|haryana|himachal pradesh|jharkhand|karnataka|kerala|madhya pradesh|maharashtra|manipur|meghalaya|mizoram|nagaland|odisha|punjab|rajasthan|sikkim|tamil nadu|telangana|tripura|uttar pradesh|uttarakhand|west bengal)\b", lowered)
        occupations = [word for word in ("farmer", "student", "fisherman", "artisan", "worker", "teacher", "driver", "entrepreneur") if re.search(rf"\b{word}\b", lowered)]
        caste = []
        for term, value in (("obc", CasteCategory.OBC), ("scheduled caste", CasteCategory.SC), ("sc", CasteCategory.SC), ("scheduled tribe", CasteCategory.ST), ("st", CasteCategory.ST), ("ews", CasteCategory.EWS)):
            if re.search(rf"\b{term}\b", lowered):
                caste.append(value)
        return EligibilityCriteria(
            age_min=age_min,
            age_max=age_max,
            income_max=income_max,
            gender=gender,
            caste_category=list(dict.fromkeys(caste)) or None,
            state=list(dict.fromkeys(state_terms)) or None,
            occupation=occupations or None,
        )

    @staticmethod
    def _number_after(text: str, pattern: str) -> int | None:
        match = re.search(pattern, text, re.I)
        return int(match.group(1)) if match else None

    @staticmethod
    def _money_after(text: str, prefix_pattern: str) -> int | None:
        match = re.search(prefix_pattern + r"(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lakhs|crore|crores)?", text, re.I)
        if not match:
            return None
        value = float(match.group(1).replace(",", ""))
        unit = (match.group(2) or "").lower()
        multiplier = 100_000 if unit.startswith("lakh") else 10_000_000 if unit.startswith("crore") else 1
        return int(value * multiplier)

    @staticmethod
    def _map_category(raw: str) -> SchemeCategory:
        value = raw.lower()
        mapping = {
            "agriculture": SchemeCategory.AGRICULTURE,
            "farmer": SchemeCategory.AGRICULTURE,
            "health": SchemeCategory.HEALTHCARE,
            "healthcare": SchemeCategory.HEALTHCARE,
            "education": SchemeCategory.EDUCATION,
            "housing": SchemeCategory.HOUSING,
            "pension": SchemeCategory.PENSION,
            "employment": SchemeCategory.EMPLOYMENT,
            "women": SchemeCategory.WOMEN_CHILD,
            "disability": SchemeCategory.DISABILITY,
        }
        return mapping.get(value, SchemeCategory.OTHER)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape myScheme.gov.in into the existing Scheme schema")
    parser.add_argument("--listing-url", default=DEFAULT_LISTING_URL)
    parser.add_argument("--limit", type=int, help="Scrape only the first N discovered schemes")
    parser.add_argument("--output", default="data/myscheme_schemes.json")
    parser.add_argument("--failures", default="data/myscheme_failed.json")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    scraper = MySchemePlaywrightScraper(retries=args.retries, delay_seconds=args.delay)
    report = scraper.scrape_listing(args.listing_url, limit=args.limit)
    scraper.write_report(report, args.output, args.failures)
    print(json.dumps({
        "discovered": len(report.discovered_urls),
        "successful": report.successful_count,
        "failed": report.failed_count,
        "output": args.output,
        "failures": args.failures,
    }, indent=2))


if __name__ == "__main__":
    main()
