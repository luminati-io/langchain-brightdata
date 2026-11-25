"""Shared test setup. Every test runs offline with a fake API key."""

import pytest

FAKE_API_KEY = "test-key"


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Replace any real BRIGHT_DATA_API_KEY on this machine with a fake one."""
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", FAKE_API_KEY)
    return FAKE_API_KEY
