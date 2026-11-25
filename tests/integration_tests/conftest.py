"""Setup for the live tests. They make real Bright Data calls with a test key."""

import os

import pytest

TEST_KEY_ENV = "BRIGHTDATA_TEST_API_KEY"


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Replace the offline suite's fake key with the real test key, or skip."""
    key = os.environ.get(TEST_KEY_ENV, "").strip()
    if not key:
        pytest.skip(f"not checked: {TEST_KEY_ENV} is not set")
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", key)
    return key
