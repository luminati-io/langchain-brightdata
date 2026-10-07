"""Replay tests built from real Bright Data replies.

The fixtures in tests/fixtures/ are scrubbed replies recorded on 2026-10-05 and
copied unchanged from PR-monster (profiles/fixtures/). Each test serves one of
them from a `responses` mock, runs the real tool, and checks two things: the
tool sent the request Bright Data expects, and the recorded reply comes back
through the tool intact. No network, no real key: tests/conftest.py sets
BRIGHT_DATA_API_KEY to test-key for every test.

The reply checks mirror PR-monster's fixtures/expect.yaml, so both repos agree
on what a real reply looks like.

Version note: on langchain-core 1.x (1.2.5 and later) `invoke` fills every
argument the caller left out from the input schema's defaults, which overrides
the tool's own fields (BrightDataUnlocker(zone="x") still sends "unlocker", and
BrightDataSERP sends brd_json=1 although its parse_results field is False). On
0.3.x it does not. That is a bug for a later PR, so nothing here depends on it:
SERP passes parse_results explicitly and every tool keeps its default zone,
which is the same on both lines.
"""

import json
import re
from pathlib import Path

import pytest
import responses
from langchain_core.tools import ToolException
from responses import matchers

from langchain_brightdata import BrightDataSERP, BrightDataUnlocker, BrightDataWebScraperAPI

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
FIXTURE_FILES = ["serp-api.json", "web-unlocker.json", "web-scraper-api.json"]

REQUEST_URL = "https://api.brightdata.com/request"
SCRAPE_URL = "https://api.brightdata.com/datasets/v3/scrape"
AMAZON_DATASET_ID = "gd_l7q7dkf244hwjntr0"


@pytest.fixture
def rsps():
    # Fails the test if a mocked call is never made, and refuses any call
    # that matches no mock instead of letting it reach the network.
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def replay(rsps, url, fixture, match=()):
    """Serve a recorded reply with its recorded status and content type."""
    reply = fixture["reply"]
    body = reply["body"]
    rsps.add(
        responses.POST,
        url,
        body=body if isinstance(body, str) else json.dumps(body),
        status=reply["status"],
        content_type=reply["headers"]["content-type"],
        match=list(match),
    )


def sent(rsps, index=0):
    request = rsps.calls[index].request
    return request, json.loads(request.body)


def counted(items, has, lacks=()):
    """Items carrying every `has` field (non-empty) and no `lacks` field."""
    return [
        item
        for item in items
        if all(item.get(field) for field in has) and not any(field in item for field in lacks)
    ]


def test_serp_replays_recorded_reply(rsps):
    replay(rsps, REQUEST_URL, load("serp-api.json"))

    # parse_results=True so the request carries brd_json=1 like the recording.
    # Passed explicitly: its effective default differs by langchain-core line.
    output = BrightDataSERP().invoke(
        {"query": "python programming language", "parse_results": True}
    )

    organic = json.loads(output)["organic"]
    assert len(counted(organic, has=["title", "link", "description"])) >= 3

    request, payload = sent(rsps)
    assert payload["zone"] == "serp"
    assert "brd_json=1" in payload["url"]
    assert request.headers["Authorization"] == "Bearer test-key"


def test_unlocker_replays_recorded_reply(rsps):
    fixture = load("web-unlocker.json")
    replay(rsps, REQUEST_URL, fixture)

    output = BrightDataUnlocker().invoke({"url": "https://books.toscrape.com/"})

    assert "Books to Scrape" in output
    assert len(output) >= 1024
    request, payload = sent(rsps)
    assert payload == {"zone": "unlocker", "url": "https://books.toscrape.com/", "format": "raw"}
    assert request.headers["Authorization"] == "Bearer test-key"


def test_scraper_replays_recorded_reply(rsps):
    # Matches URL and query only: the recording sent {"input": [...]} with
    # format=json, while the package sends a bare list without format, so the
    # body shape is not pinned here and extra query params are allowed.
    replay(
        rsps,
        SCRAPE_URL,
        load("web-scraper-api.json"),
        match=[
            matchers.query_param_matcher(
                {"dataset_id": AMAZON_DATASET_ID, "include_errors": "true"},
                strict_match=False,
            )
        ],
    )

    output = BrightDataWebScraperAPI().invoke(
        {"dataset_type": "amazon_product", "url": "https://www.amazon.com/dp/B0863TXGM3"}
    )

    records = json.loads(output)
    assert len(counted(records, has=["url", "title", "asin"], lacks=["error", "error_code"])) >= 1
    request, _ = sent(rsps)
    assert "https://www.amazon.com/dp/B0863TXGM3" in request.body.decode("utf-8")
    assert request.headers["Authorization"] == "Bearer test-key"


def test_scraper_401_raises_tool_exception(rsps):
    # Synthetic, not recorded: what Bright Data says to a bad key.
    rsps.add(
        responses.POST,
        SCRAPE_URL,
        json={"error": "Unauthorized"},
        status=401,
        match=[
            matchers.query_param_matcher(
                {"dataset_id": AMAZON_DATASET_ID, "include_errors": "true"},
                strict_match=False,
            )
        ],
    )
    # handle_tool_error=False so invoke raises instead of returning the text.
    tool = BrightDataWebScraperAPI(handle_tool_error=False)

    with pytest.raises(ToolException, match="401"):
        tool.invoke(
            {"dataset_type": "amazon_product", "url": "https://www.amazon.com/dp/B0863TXGM3"}
        )


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_fixture_is_scrubbed(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for secret in ("Bearer", "Authorization", "lum-customer"):
        assert secret.lower() not in text.lower(), f"{name} contains {secret!r}"

    zone = load(name)["meta"]["request"].get("zone")
    if zone is not None:
        assert re.fullmatch(r"<[A-Z0-9_]+>", zone), f"{name} has a real zone name: {zone!r}"


def test_recorded_zones_are_checked():
    # Guards the scrub test above from passing on fixtures that carry no zone.
    zones = [load(name)["meta"]["request"].get("zone") for name in FIXTURE_FILES]
    assert sum(zone is not None for zone in zones) >= 2
