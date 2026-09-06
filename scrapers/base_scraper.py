"""
Abstract base class every source-specific scraper implements.

Design: separate "getting the raw page" from "turning it into a Scheme".
This lets you unit-test parse() against saved HTML fixtures without
hitting the network every time (important once you're scraping dozens
of pages and don't want to hammer government servers during dev).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date

import requests

from schema import Scheme

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    # Identify honestly. Don't spoof a browser UA to dodge scraping
    # etiquette on government sites — check robots.txt too.
    "User-Agent": "GovSchemeEligibilityBot/0.1 (student project; contact: you@example.com)"
}


class ScraperError(Exception):
    """Raised when a page can't be fetched or doesn't match the expected structure."""


class BaseSchemeScraper(ABC):
    """
    Subclass per source (myscheme.gov.in, a state welfare site, a PDF
    guideline doc, ...). Each subclass only needs to implement
    `parse_html`; fetch/orchestration is shared here.
    """

    source_name: str = "unknown"

    def fetch_html(self, url: str, timeout: int = 15) -> str:
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ScraperError(f"Failed to fetch {url}: {e}") from e
        return resp.text

    @abstractmethod
    def parse_html(self, html: str, source_url: str) -> Scheme:
        """
        Parse raw HTML into a validated Scheme object.
        Must raise ScraperError (not a bare exception) on malformed input,
        so the calling pipeline can log-and-skip rather than crash on
        one bad page out of hundreds.
        """
        raise NotImplementedError

    def scrape(self, url: str) -> Scheme:
        """Fetch + parse in one call. Use for production runs."""
        html = self.fetch_html(url)
        return self.parse_html(html, source_url=url)

    def scrape_from_file(self, html_path: str, source_url: str) -> Scheme:
        """
        Parse a locally saved HTML file instead of fetching live.
        Use this for: (a) unit tests against fixtures, (b) re-parsing
        after you tweak parse_html without re-hitting the network,
        (c) working offline if a site is unreachable from your dev box.
        """
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        return self.parse_html(html, source_url=source_url)

    @staticmethod
    def today() -> date:
        return date.today()
