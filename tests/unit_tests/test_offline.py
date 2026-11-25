"""Guards for the test harness itself: no network, no real key."""

import os

import pytest
import requests
from pytest_socket import SocketBlockedError

from langchain_brightdata import BrightDataSERP


# pytest-socket 0.8 warns before it raises; the block itself is what this test checks.
@pytest.mark.filterwarnings("ignore:A test tried")
def test_network_is_blocked() -> None:
    # Fails if pytest runs without --disable-socket (see [tool.pytest.ini_options]).
    # Targets a closed local port, so even a broken harness sends nothing to Bright Data.
    with pytest.raises(SocketBlockedError):
        requests.get("http://127.0.0.1:9/", timeout=5)


def test_only_fake_key_is_seen(fake_api_key: str) -> None:
    assert fake_api_key == "test-key"
    assert os.environ["BRIGHT_DATA_API_KEY"] == fake_api_key
    tool = BrightDataSERP()
    assert tool.api_wrapper.bright_data_api_key.get_secret_value() == fake_api_key
