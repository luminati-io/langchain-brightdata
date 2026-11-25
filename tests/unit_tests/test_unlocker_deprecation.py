"""BrightDataUnlocker still works, and tells people to move to BrightDataWebFetch."""

import warnings

import pytest
import responses

from langchain_brightdata import BrightDataUnlocker, BrightDataWebFetch

REQUEST_URL = "https://api.brightdata.com/request"
PAGE = "https://example.com"


@pytest.fixture
def rsps():
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


def old_tool():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return BrightDataUnlocker()


def test_creating_the_old_tool_warns_and_names_the_new_one():
    with pytest.warns(DeprecationWarning, match="BrightDataWebFetch"):
        BrightDataUnlocker()


def test_the_new_tool_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        BrightDataWebFetch()


def test_old_tool_still_returns_the_page_when_the_zone_exists(rsps):
    rsps.add(responses.POST, REQUEST_URL, body="<html>Example Domain</html>", status=200)

    assert old_tool().invoke({"url": PAGE}) == "<html>Example Domain</html>"


@pytest.mark.parametrize(
    "reply",
    [
        {"body": 'zone "unlocker" not found', "status": 400},
        {"body": "", "status": 200, "headers": {"x-brd-err-code": "client_10002"}},
    ],
)
def test_missing_zone_points_to_the_new_tool_and_creates_nothing(rsps, reply):
    rsps.add(responses.POST, REQUEST_URL, **reply)

    result = old_tool().invoke({"url": PAGE})

    assert 'zone "unlocker" does not exist' in result
    assert "BrightDataWebFetch" in result
    assert len(rsps.calls) == 1
