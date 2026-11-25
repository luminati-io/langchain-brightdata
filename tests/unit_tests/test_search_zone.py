"""The search tool creates its zone when the account does not have it.

A new Bright Data account has no SERP API zone, so the first search used to come
back as the text `zone "serp" not found`. Now the wrapper creates the zone and
keeps searching until the zone answers.

The replies below copy what Bright Data sent on 2026-11-25: a missing zone is
either HTTP 400 with `zone "<name>" not found`, or HTTP 200 with an empty body
and the header `x-brd-err-code: client_10002`. A zone created through POST /zone
went on answering "not found" for up to about two minutes.
"""

import json

import pytest
import requests
import responses

from langchain_brightdata import BrightDataSERP, _utilities
from langchain_brightdata._utilities import BrightDataSERPAPIWrapper

REQUEST_URL = "https://api.brightdata.com/request"
ZONE_URL = "https://api.brightdata.com/zone"
RESULTS = json.dumps({"organic": [{"link": "https://brightdata.com/", "title": "Bright Data"}]})


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Polling never really sleeps in tests."""
    monkeypatch.setattr(_utilities.time, "sleep", lambda seconds: None)


def missing_400(rsps, zone="serp"):
    rsps.add(responses.POST, REQUEST_URL, body=f'zone "{zone}" not found', status=400)


def missing_header(rsps):
    rsps.add(
        responses.POST,
        REQUEST_URL,
        body="",
        status=200,
        headers={"x-brd-err-code": "client_10002", "x-brd-error": "Zone not found"},
    )


def found(rsps):
    rsps.add(responses.POST, REQUEST_URL, body=RESULTS, status=200)


def created(rsps):
    rsps.add(responses.POST, ZONE_URL, json={"zone": {"created": "2026-11-25"}}, status=200)


def paths(rsps):
    return [call.request.url.replace("https://api.brightdata.com", "") for call in rsps.calls]


def test_existing_zone_makes_one_call(rsps):
    found(rsps)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert result == RESULTS
    assert paths(rsps) == ["/request"]


def test_missing_zone_is_created_then_searched(rsps):
    missing_400(rsps)
    created(rsps)
    found(rsps)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert result == RESULTS
    assert paths(rsps) == ["/request", "/zone", "/request"]
    assert json.loads(rsps.calls[1].request.body) == {
        "zone": {"name": "serp", "type": "unblocker"},
        "plan": {"type": "unblocker", "serp": True},
    }
    assert rsps.calls[1].request.headers["Authorization"] == "Bearer test-key"


def test_missing_zone_reported_in_headers_is_created(rsps):
    missing_header(rsps)
    created(rsps)
    found(rsps)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert result == RESULTS
    assert paths(rsps) == ["/request", "/zone", "/request"]


def test_new_zone_is_polled_until_it_answers(rsps):
    missing_400(rsps)
    created(rsps)
    missing_header(rsps)
    missing_400(rsps)
    found(rsps)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert result == RESULTS
    assert paths(rsps) == ["/request", "/zone", "/request", "/request", "/request"]


def test_slow_create_call_still_waits_for_the_zone(rsps):
    # POST /zone took 32-52 s live. If it times out here the zone is still created.
    missing_400(rsps)
    rsps.add(responses.POST, ZONE_URL, body=requests.exceptions.ReadTimeout("slow"))
    found(rsps)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert result == RESULTS


def test_refused_create_says_how_to_fix_it(rsps):
    missing_400(rsps)
    rsps.add(responses.POST, ZONE_URL, body="Forbidden", status=403)

    with pytest.raises(ValueError) as error:
        BrightDataSERPAPIWrapper().get_search_results("bright data")

    message = str(error.value)
    assert 'zone "serp"' in message
    assert "could not be created" in message
    assert "https://brightdata.com/cp/zones" in message
    assert "403" in message
    assert paths(rsps) == ["/request", "/zone"]


def test_zone_that_never_answers_stops_with_a_clear_error(rsps, monkeypatch):
    monkeypatch.setattr(_utilities, "ZONE_READY_TIMEOUT", 0)
    missing_400(rsps)
    created(rsps)
    missing_header(rsps)

    with pytest.raises(ValueError) as error:
        BrightDataSERPAPIWrapper().get_search_results("bright data")

    assert "not ready yet" in str(error.value)
    assert paths(rsps) == ["/request", "/zone", "/request"]


def test_empty_reply_from_a_new_zone_is_polled_too(rsps):
    # Seen live on 2026-11-25: a new zone answered 200 with an empty body before it worked.
    missing_400(rsps)
    created(rsps)
    rsps.add(responses.POST, REQUEST_URL, body="", status=200)
    found(rsps)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert result == RESULTS
    assert paths(rsps) == ["/request", "/zone", "/request", "/request"]


def test_empty_replies_stop_at_the_deadline_with_the_reason(rsps, monkeypatch):
    monkeypatch.setattr(_utilities, "ZONE_READY_TIMEOUT", 0)
    missing_400(rsps)
    created(rsps)
    rsps.add(
        responses.POST,
        REQUEST_URL,
        body="",
        status=200,
        headers={"x-brd-error": "redirect location was rejected"},
    )

    with pytest.raises(ValueError) as error:
        BrightDataSERPAPIWrapper().get_search_results("bright data")

    assert "not ready yet" in str(error.value)
    assert "redirect location was rejected" in str(error.value)
    assert paths(rsps) == ["/request", "/zone", "/request"]


def test_the_wait_is_bounded_by_the_clock(rsps, monkeypatch):
    """However long the zone stays missing, polling ends once ZONE_READY_TIMEOUT has passed."""
    clock = {"now": 0.0}
    monkeypatch.setattr(_utilities.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        _utilities.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds)
    )
    rsps.assert_all_requests_are_fired = False
    created(rsps)
    rsps.add(responses.POST, REQUEST_URL, body='zone "serp" not found', status=400)

    with pytest.raises(ValueError, match="not ready yet"):
        BrightDataSERPAPIWrapper().get_search_results("bright data")

    polls = len([path for path in paths(rsps) if path == "/request"]) - 1
    assert polls == _utilities.ZONE_READY_TIMEOUT // _utilities.ZONE_READY_POLL + 1


def test_tool_gives_the_agent_the_fix_as_text(rsps):
    missing_400(rsps)
    rsps.add(responses.POST, ZONE_URL, body="Forbidden", status=403)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert "could not be created" in result
    assert "https://brightdata.com/cp/zones" in result


def test_other_errors_do_not_create_a_zone(rsps):
    rsps.add(responses.POST, REQUEST_URL, body="Invalid token", status=401)

    result = BrightDataSERP().invoke({"query": "bright data"})

    assert result == "Invalid token"
    assert paths(rsps) == ["/request"]


def test_a_custom_zone_name_is_the_one_created(rsps):
    missing_400(rsps, zone="my_serp")
    created(rsps)
    found(rsps)

    BrightDataSERPAPIWrapper().get_search_results("bright data", zone="my_serp")

    assert json.loads(rsps.calls[1].request.body)["zone"]["name"] == "my_serp"
