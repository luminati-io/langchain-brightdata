"""BrightDataWebFetch reads a page through the Fetch API. It needs no zone.

RECORD copies the fields Bright Data returned for https://example.com on
2026-11-25. ERROR_RECORD copies a dead-page reply from the same API.
"""

import json

import pytest
import requests
import responses
from responses import matchers

from langchain_brightdata import BrightDataWebFetch
from langchain_brightdata._utilities import BrightDataWebFetchAPIWrapper

SCRAPE_URL = "https://api.brightdata.com/datasets/v3/scrape"
QUERY = {"dataset_id": "gd_m6gjtfmeh43we6cqc", "format": "json", "include_errors": "true"}
PAGE = "https://example.com"
MARKDOWN = "This domain is for use in documentation examples without needing permission."
RECORD = {
    "markdown": MARKDOWN,
    "url": "https://example.com/",
    "html2text": "This domain is for use in documentation examples.\n",
    "page_html": "<!doctype html><html lang=en><head><title>Example Domain</title></head></html>",
    "page_title": "Example Domain",
    "input": {"url": PAGE},
}
ERROR_RECORD = {
    "input": {"url": "https://example.com/missing"},
    "error": "The navigation resulted in a dead page (404 status code)",
    "error_code": "dead_page",
}


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


def reply(rsps, body, status=200):
    rsps.add(
        responses.POST,
        SCRAPE_URL,
        json=body,
        status=status,
        match=[matchers.query_param_matcher(QUERY)],
    )


def test_sends_the_fetch_api_request_and_returns_markdown(rsps):
    reply(rsps, [RECORD])

    result = BrightDataWebFetch().invoke({"url": PAGE})

    assert result == MARKDOWN
    request = rsps.calls[0].request
    assert json.loads(request.body) == [{"url": PAGE}]
    assert request.headers["Authorization"] == "Bearer test-key"
    assert "zone" not in request.url
    assert len(rsps.calls) == 1


@pytest.mark.parametrize(
    "format, expected",
    [("markdown", MARKDOWN), ("text", RECORD["html2text"]), ("html", RECORD["page_html"])],
)
def test_each_format_returns_its_field(rsps, format, expected):
    reply(rsps, [RECORD])

    assert BrightDataWebFetch().invoke({"url": PAGE, "format": format}) == expected


def test_format_set_on_the_tool_is_the_default(rsps):
    reply(rsps, [RECORD])

    assert BrightDataWebFetch(format="html").invoke({"url": PAGE}) == RECORD["page_html"]


def test_empty_markdown_falls_back_to_text(rsps):
    reply(rsps, [dict(RECORD, markdown="")])

    assert BrightDataWebFetch().invoke({"url": PAGE}) == RECORD["html2text"]


def test_page_error_is_reported_not_returned_as_content(rsps):
    reply(rsps, [ERROR_RECORD])

    result = BrightDataWebFetch().invoke({"url": "https://example.com/missing"})

    assert "Could not read https://example.com/missing" in result
    assert "dead page" in result
    assert "dead_page" in result


def test_page_with_no_text_is_an_error(rsps):
    reply(rsps, [dict(RECORD, markdown="", html2text="  ", page_html="")])

    result = BrightDataWebFetch().invoke({"url": PAGE})

    assert "returned no text" in result


def test_empty_reply_is_an_error(rsps):
    reply(rsps, [])

    assert "returned nothing" in BrightDataWebFetch().invoke({"url": PAGE})


def test_still_running_reply_is_a_timeout_error(rsps):
    reply(rsps, {"snapshot_id": "sd_abc", "message": "still running"}, status=202)

    result = BrightDataWebFetch().invoke({"url": PAGE})

    assert "did not load in time" in result


def test_bad_key_says_so(rsps):
    rsps.add(responses.POST, SCRAPE_URL, body="Invalid token", status=401)

    result = BrightDataWebFetch().invoke({"url": PAGE})

    assert "401" in result
    assert "Invalid token" in result
    assert "API key" in result


def test_other_http_errors_carry_status_and_text(rsps):
    rsps.add(responses.POST, SCRAPE_URL, body="bad input", status=400)

    result = BrightDataWebFetch().invoke({"url": PAGE})

    assert "400" in result
    assert "bad input" in result


def test_network_timeout_is_a_clear_error(rsps):
    rsps.add(responses.POST, SCRAPE_URL, body=requests.exceptions.ReadTimeout("slow"))

    result = BrightDataWebFetch().invoke({"url": PAGE})

    assert "did not load in time" in result


def test_wrapper_raises_so_developers_can_catch(rsps):
    reply(rsps, [ERROR_RECORD])

    with pytest.raises(ValueError, match="dead_page"):
        BrightDataWebFetchAPIWrapper().fetch_page("https://example.com/missing")


def test_the_model_cannot_set_account_settings():
    fields = BrightDataWebFetch().get_input_schema().model_fields

    assert list(fields) == ["url", "format"]
