"""Live end-to-end tests: one real call per tool, the way a new user would make it.

Each test builds the tool with its defaults and only an API key, then checks for
content that only a real answer can contain. They cost a few cents per run.

Run them with:  python -m pytest -m live tests/integration_tests
They are left out of the default run and skip when BRIGHTDATA_TEST_API_KEY is not set.
"""

import json
import uuid

import pytest
import requests

from langchain_brightdata import (
    BrightDataSERP,
    BrightDataUnlocker,
    BrightDataWebFetch,
    BrightDataWebScraperAPI,
)
from langchain_brightdata._utilities import BrightDataSERPAPIWrapper

pytestmark = [pytest.mark.live, pytest.mark.enable_socket]


def _text(result: object) -> str:
    return result if isinstance(result, str) else json.dumps(result, default=str)


def _shown(text: str) -> str:
    return repr(text[:300])


def _has_search_results(text: str) -> bool:
    """Real results: parsed JSON with organic links, or a full raw results page.

    Checks the shape, not one site: which sites rank changes by day and by proxy location.
    """
    try:
        organic = json.loads(text).get("organic") or []
    except (ValueError, AttributeError):
        return len(text) > 5000 and "bright data" in text.lower()
    return any(isinstance(item, dict) and item.get("link") for item in organic)


def test_search_returns_real_results() -> None:
    text = _text(BrightDataSERP().invoke({"query": "bright data"}))

    assert _has_search_results(text), (
        "Search for 'bright data' did not return search results. "
        f"The tool returned: {_shown(text)}"
    )


def test_search_creates_a_missing_zone(fake_api_key: str) -> None:
    """A zone name the account has never had: the wrapper creates it and still returns results.

    Takes up to about five minutes. The zone is deleted afterwards.
    """
    zone = f"lc_test_{uuid.uuid4().hex[:10]}"
    try:
        text = BrightDataSERPAPIWrapper().get_search_results(
            "bright data", zone=zone, parse_results=True
        )
    finally:
        requests.delete(
            "https://api.brightdata.com/zone",
            json={"zone": zone},
            headers={"Authorization": f"Bearer {fake_api_key}"},
            timeout=120,
        )

    assert _has_search_results(text), (
        f"Search through the new zone {zone} did not return search results. "
        f"The wrapper returned: {_shown(text)}"
    )


def test_web_fetch_returns_the_page() -> None:
    text = _text(BrightDataWebFetch().invoke({"url": "https://example.com"}))

    assert "documentation examples" in text, (
        "Reading https://example.com with BrightDataWebFetch did not return the page text. "
        f"The tool returned: {_shown(text)}"
    )


def test_web_fetch_reports_a_missing_page() -> None:
    text = _text(BrightDataWebFetch().invoke({"url": "https://example.com/no-such-page-404"}))

    assert "Could not read" in text, (
        "A page that does not exist should come back as an error the agent can read. "
        f"The tool returned: {_shown(text)}"
    )


def test_old_unlocker_reads_the_page_or_points_to_web_fetch() -> None:
    """The deprecated tool needs an "unlocker" zone. Without one it must name the new tool."""
    with pytest.warns(DeprecationWarning, match="BrightDataWebFetch"):
        tool = BrightDataUnlocker()

    text = _text(tool.invoke({"url": "https://example.com"}))

    assert "Example Domain" in text or "BrightDataWebFetch" in text, (
        "BrightDataUnlocker returned neither the page nor a pointer to BrightDataWebFetch. "
        f"The tool returned: {_shown(text)}"
    )


def test_scraper_returns_a_record() -> None:
    text = _text(
        BrightDataWebScraperAPI().invoke(
            {
                "url": "https://www.linkedin.com/company/bright-data",
                "dataset_type": "linkedin_company_profile",
            }
        )
    )

    assert '"id":"bright-data"' in text.replace(" ", ""), (
        "The LinkedIn company scraper did not return the Bright Data record. "
        f"The tool returned: {_shown(text)}"
    )
