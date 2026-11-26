"""A failed search comes back as a clear error, never as an empty or odd "result".

Bright Data reports most search failures as HTTP 200 with an empty body and the
reason in a response header, so the old code handed the agent an empty string or
the error text as if it were the results.

FAILURES is the answer key: every reply below was sent by the real API on
2026-11-26, or is listed in Bright Data's error catalog
(https://docs.brightdata.com/scraping-automation/serp-api/debugging).
The clean replies further down are the controls: they must pass through untouched.
"""

import json

import pytest
import requests
import responses

from langchain_brightdata import BrightDataSERP, _utilities
from langchain_brightdata._utilities import BrightDataSERPAPIWrapper

REQUEST_URL = "https://api.brightdata.com/request"
RESULTS = json.dumps({"organic": [{"link": "https://brightdata.com/", "title": "Bright Data"}]})
RECENTLY_FAILED = (
    "This query recently failed and cannot be attempted at this time. "
    "Please try again later, after a minimum of 15 seconds."
)

# name -> a reply that is a failed search and is worth one more try
FAILURES = {
    "redirect rejected": {
        "status": 200,
        "body": "",
        "headers": {"x-brd-error": "redirect location was rejected"},
    },
    "query blocked for 15 seconds": {
        "status": 200,
        "body": RECENTLY_FAILED,
        "headers": {"x-brd-error": RECENTLY_FAILED, "x-brd-error-code": "failed_query_rejected"},
    },
    "captcha": {
        "status": 200,
        "body": "",
        "headers": {"x-brd-error": "google_captcha detected"},
    },
    "page did not load": {
        "status": 200,
        "body": "",
        "headers": {"x-brd-error": 'waiting for selector "#main" failed: timeout 30000'},
    },
    "short reply": {
        "status": 200,
        "body": "",
        "headers": {"x-brd-error": "response is shorter than expected"},
    },
    "reason in the older header": {
        "status": 200,
        "body": "",
        "headers": {"x-brd-err-msg": "reject element found"},
    },
    "challenge page (catalog)": {
        "status": 502,
        "body": "",
        "headers": {"x-brd-error": "challenge page detected", "x-brd-error-code": "verifying"},
    },
    "empty reply with no reason": {"status": 200, "body": "", "headers": {}},
    "server error": {"status": 500, "body": "Internal Server Error", "headers": {}},
}

# name -> (a failed search that would fail the same way again, the next step it must name)
NO_RETRY = {
    "bad key": ({"status": 401, "body": "Invalid token", "headers": {}}, "API key"),
    "throttled": (
        {
            "status": 429,
            "body": "",
            "headers": {
                "x-brd-error": "The request was auto-throttled due to low success rate",
                "x-brd-error-code": "sr_rate_limit",
            },
        },
        "fewer searches",
    ),
    "account rate limit": (
        {
            "status": 429,
            "body": "",
            "headers": {
                "x-brd-error": "Your account exceeded the allowed rate limits.",
                "x-brd-error-code": "client_10110",
            },
        },
        "fewer searches",
    ),
}


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture
def waits(monkeypatch):
    """Records every wait instead of sleeping."""
    seen = []
    monkeypatch.setattr(_utilities.time, "sleep", seen.append)
    return seen


def search(**kwargs):
    return BrightDataSERPAPIWrapper().get_search_results("pizza", **kwargs)


@pytest.mark.parametrize("name", FAILURES)
def test_a_failed_search_is_retried_once_then_raised_with_the_reason(rsps, waits, name):
    reply = FAILURES[name]
    rsps.add(responses.POST, REQUEST_URL, **reply)
    rsps.add(responses.POST, REQUEST_URL, **reply)

    with pytest.raises(ValueError) as error:
        search()

    message = str(error.value)
    assert 'Google search for "pizza" failed after 2 tries' in message
    reason = reply["headers"].get("x-brd-error") or reply["headers"].get("x-brd-err-msg")
    assert (reason or f"HTTP {reply['status']}") in message
    assert "Wait 15 seconds" in message and "reword" in message
    assert len(rsps.calls) == 2
    assert waits == [15]


@pytest.mark.parametrize("name", FAILURES)
def test_a_failure_followed_by_results_returns_the_results(rsps, waits, name):
    rsps.add(responses.POST, REQUEST_URL, **FAILURES[name])
    rsps.add(responses.POST, REQUEST_URL, body=RESULTS, status=200)

    assert search() == RESULTS
    assert waits == [15]


@pytest.mark.parametrize("name", NO_RETRY)
def test_failures_that_would_repeat_are_not_retried(rsps, waits, name):
    reply, next_step = NO_RETRY[name]
    rsps.add(responses.POST, REQUEST_URL, **reply)

    with pytest.raises(ValueError, match=next_step):
        search()

    assert len(rsps.calls) == 1
    assert waits == []


def test_the_error_code_is_shown_next_to_the_reason(rsps, waits):
    reply = FAILURES["query blocked for 15 seconds"]
    rsps.add(responses.POST, REQUEST_URL, **reply)
    rsps.add(responses.POST, REQUEST_URL, **reply)

    with pytest.raises(ValueError, match=r"\[failed_query_rejected\]"):
        search()


# Controls: real results must come back untouched, in one call, with no waiting.
@pytest.mark.parametrize(
    "body",
    [
        RESULTS,
        "<html><body>" + "result " * 500 + "</body></html>",
        # a results page that happens to quote an error sentence is still results
        json.dumps({"organic": [{"title": "Fix: redirect location was rejected", "link": "x"}]}),
    ],
)
def test_real_results_pass_through_untouched(rsps, waits, body):
    rsps.add(
        responses.POST,
        REQUEST_URL,
        body=body,
        status=200,
        headers={"x-brd-serp-warn": "num parameter is not supported"},
    )

    assert search() == body
    assert len(rsps.calls) == 1
    assert waits == []


@pytest.mark.parametrize("engine", ["google", "bing"])
def test_google_and_bing_are_accepted(rsps, waits, engine):
    rsps.add(responses.POST, REQUEST_URL, body=RESULTS, status=200)

    assert search(search_engine=engine) == RESULTS
    sent = json.loads(rsps.calls[0].request.body)["url"]
    assert sent.startswith(f"https://www.{engine}.com/search?q=pizza")


@pytest.mark.parametrize("engine", ["yahoo", "duckduckgo", "yandex", "baidu", "naver", "", None])
def test_other_engines_are_refused_before_any_call(engine):
    with responses.RequestsMock() as mock:
        with pytest.raises(ValueError, match='search_engine must be "google" or "bing"'):
            search(search_engine=engine)
        assert len(mock.calls) == 0


def test_the_agent_sees_the_error_as_text_not_as_a_result(rsps, waits):
    reply = FAILURES["redirect rejected"]
    rsps.add(responses.POST, REQUEST_URL, **reply)
    rsps.add(responses.POST, REQUEST_URL, **reply)

    shown = BrightDataSERP().invoke({"query": "pizza"})

    assert shown.startswith('Google search for "pizza" failed after 2 tries')
    assert "redirect location was rejected" in shown
    assert "Wait 15 seconds" in shown


def test_the_tool_offers_only_google_and_bing_to_the_model():
    schema = BrightDataSERP().args_schema.model_json_schema()
    options = json.dumps(schema["properties"]["search_engine"])
    assert '"google"' in options and '"bing"' in options
    assert "yahoo" not in options


def test_a_refused_engine_reaches_the_agent_as_text_not_as_an_exception():
    with responses.RequestsMock() as mock:
        shown = BrightDataSERP().invoke({"query": "pizza", "search_engine": "yahoo"})
        assert len(mock.calls) == 0

    assert shown == 'search_engine must be "google" or "bing". Got "yahoo".'


@pytest.mark.parametrize("engine", ["Google", "BING", " bing "])
def test_engine_names_are_not_case_sensitive(rsps, waits, engine):
    rsps.add(responses.POST, REQUEST_URL, body=RESULTS, status=200)

    assert search(search_engine=engine) == RESULTS
    sent = json.loads(rsps.calls[0].request.body)["url"]
    assert sent.startswith(f"https://www.{engine.strip().lower()}.com/search?q=pizza")


@pytest.mark.parametrize(
    "failure, words",
    [
        (requests.exceptions.ReadTimeout("slow"), "no reply from Bright Data in 60 seconds"),
        (requests.exceptions.ConnectionError("dns"), "Could not reach Bright Data"),
    ],
)
def test_no_reply_is_a_clear_error_too(rsps, waits, failure, words):
    rsps.add(responses.POST, REQUEST_URL, body=failure)

    shown = BrightDataSERP().invoke({"query": "pizza"})

    assert words in shown and "try the search again" in shown.lower()
    assert "HTTPSConnectionPool" not in shown
    assert waits == []


# Found by an independent review of the first version of this change.
ZONE_URL = "https://api.brightdata.com/zone"


def new_zone(rsps):
    """The account has no zone: the first search says so, then the zone is created."""
    rsps.add(responses.POST, REQUEST_URL, body='zone "serp" not found', status=400)
    rsps.add(responses.POST, ZONE_URL, json={"zone": {"created": "2026-11-26"}}, status=200)


@pytest.mark.parametrize("name", NO_RETRY)
def test_a_new_zone_does_not_hide_a_failure_that_waiting_cannot_fix(rsps, waits, name):
    reply, next_step = NO_RETRY[name]
    new_zone(rsps)
    rsps.add(responses.POST, REQUEST_URL, **reply)

    with pytest.raises(ValueError, match=next_step):
        search()

    assert len(rsps.calls) == 3
    assert waits == []


def test_a_new_zone_keeps_waiting_through_the_15_second_block(rsps, waits):
    new_zone(rsps)
    rsps.add(responses.POST, REQUEST_URL, body="", status=200)
    rsps.add(responses.POST, REQUEST_URL, **FAILURES["query blocked for 15 seconds"])
    rsps.add(responses.POST, REQUEST_URL, body="", status=200)
    rsps.add(responses.POST, REQUEST_URL, body=RESULTS, status=200)

    assert search() == RESULTS
    assert waits == [5, 5, 5]


@pytest.mark.parametrize(
    "reply, next_step",
    [
        ({"status": 429, "body": "Too Many Requests", "headers": {}}, "fewer searches"),
        (
            {"status": 429, "body": "", "headers": {"x-brd-error-code": "bucket_rate_limit"}},
            "fewer searches",
        ),
        ({"status": 429, "body": "", "headers": {"x-brd-err-code": "sr_rate_limit"}}, "fewer"),
        ({"status": 400, "body": "Invalid url", "headers": {}}, "will fail the same way"),
        ({"status": 404, "body": "Not found", "headers": {}}, "will fail the same way"),
    ],
)
def test_rate_limits_and_bad_requests_are_not_retried(rsps, waits, reply, next_step):
    rsps.add(responses.POST, REQUEST_URL, **reply)

    with pytest.raises(ValueError, match=next_step) as error:
        search()

    assert "usually temporary" not in str(error.value)
    assert len(rsps.calls) == 1
    assert waits == []


@pytest.mark.parametrize("code", ["failed_query_rejected", "repeat_query_rejected"])
def test_the_15_second_block_is_retried_even_when_sent_as_http_429(rsps, waits, code):
    rsps.add(
        responses.POST,
        REQUEST_URL,
        status=429,
        body="",
        headers={"x-brd-error": RECENTLY_FAILED, "x-brd-error-code": code},
    )
    rsps.add(responses.POST, REQUEST_URL, body=RESULTS, status=200)

    assert search() == RESULTS
    assert waits == [15]


def test_a_403_shows_the_reason_bright_data_gave(rsps, waits):
    rsps.add(
        responses.POST,
        REQUEST_URL,
        status=403,
        body="",
        headers={"x-brd-error": "Zone is suspended", "x-brd-error-code": "client_10030"},
    )

    with pytest.raises(ValueError) as error:
        search()

    message = str(error.value)
    assert "Zone is suspended [client_10030]" in message
    assert "rejected the API key" not in message
    assert len(rsps.calls) == 1


def test_when_the_second_try_gets_no_reply_the_first_reason_is_kept(rsps, waits):
    rsps.add(responses.POST, REQUEST_URL, **FAILURES["captcha"])
    rsps.add(responses.POST, REQUEST_URL, body=requests.exceptions.ReadTimeout("slow"))

    with pytest.raises(ValueError) as error:
        search()

    message = str(error.value)
    assert 'Google search for "pizza" failed after 2 tries' in message
    assert "google_captcha detected" in message


def test_a_very_long_query_is_shortened_in_the_message(rsps, waits):
    reply = FAILURES["captcha"]
    rsps.add(responses.POST, REQUEST_URL, **reply)
    rsps.add(responses.POST, REQUEST_URL, **reply)

    with pytest.raises(ValueError) as error:
        BrightDataSERPAPIWrapper().get_search_results("x" * 5000)

    assert len(str(error.value)) < 500
