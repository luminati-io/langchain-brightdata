"""results_count does nothing any more, so it is not sent and the model does not see it.

Bright Data's SERP API documentation (read 2026-11-26):
- Google: "Deprecated by Google on September 11, 2025. The `num` parameter no longer
  sets how many Google results are returned."
- Bing: `count` "was deprecated by bing and is no longer supported."
Measured live the same day: asking Bing for 5 or for 30 results returned 10.

Old code that still passes results_count must keep working and be told.
"""

import json
import warnings

import pytest
import responses
from langchain_core._api import LangChainDeprecationWarning

from langchain_brightdata import BrightDataSERP
from langchain_brightdata._utilities import BrightDataSERPAPIWrapper

REQUEST_URL = "https://api.brightdata.com/request"
RESULTS = json.dumps({"organic": [{"link": "https://brightdata.com/", "title": "Bright Data"}]})


@pytest.fixture
def rsps():
    with responses.RequestsMock() as mock:
        mock.add(responses.POST, REQUEST_URL, body=RESULTS, status=200)
        yield mock


def sent_url(rsps):
    return json.loads(rsps.calls[0].request.body)["url"]


@pytest.mark.parametrize("engine", ["google", "bing"])
def test_no_result_count_is_sent(rsps, engine):
    BrightDataSERP().invoke({"query": "pizza", "search_engine": engine})

    assert "num=" not in sent_url(rsps)
    assert "count=" not in sent_url(rsps)


def test_the_model_is_not_offered_a_result_count():
    assert "results_count" not in BrightDataSERP().args


def test_a_tool_created_the_old_way_still_works_and_is_told(rsps):
    with pytest.warns(LangChainDeprecationWarning, match="results_count no longer does"):
        tool = BrightDataSERP(results_count=20)

    assert tool.invoke({"query": "pizza"}) == RESULTS
    assert "num=" not in sent_url(rsps)


def test_a_call_the_old_way_still_works(rsps):
    result = BrightDataSERP().invoke({"query": "pizza", "results_count": 20})

    assert result == RESULTS
    assert "num=" not in sent_url(rsps)


def test_the_wrapper_called_the_old_way_still_works_and_is_told(rsps):
    with pytest.warns(LangChainDeprecationWarning, match="removed in langchain-brightdata 0.4.0"):
        result = BrightDataSERPAPIWrapper().get_search_results("pizza", results_count=20)

    assert result == RESULTS
    assert "num=" not in sent_url(rsps)


def test_normal_use_gets_no_warning(rsps):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        BrightDataSERP().invoke({"query": "pizza"})


def test_the_warning_points_at_the_callers_line():
    with pytest.warns(LangChainDeprecationWarning) as caught:
        BrightDataSERP(results_count=20)

    assert caught[0].filename == __file__
