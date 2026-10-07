"""What the LLM sees from each tool must match snapshots/tool_contract.json.

Checks tool names, arg field names, required fields, dataset_type values and
dataset ids. Fields only, not the full JSON schema (that differs between
langchain-core 0.3 and 1.x).

A failure here means a change to what an LLM sees or to which dataset is
called. If the change is intended, regenerate the snapshot and review the diff:

    UPDATE_TOOL_CONTRACT=1 pytest tests/unit_tests/test_tool_contract.py

(PowerShell: $env:UPDATE_TOOL_CONTRACT="1"; pytest tests/unit_tests/test_tool_contract.py;
Remove-Item Env:UPDATE_TOOL_CONTRACT). The snapshot is never rewritten without the flag.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, get_args

import pytest
from langchain_core.tools import BaseTool

from langchain_brightdata import BrightDataSERP, BrightDataUnlocker, BrightDataWebScraperAPI
from langchain_brightdata.brightdata_scraper import DATASET_MAPPING

SNAPSHOT = Path(__file__).parent / "snapshots" / "tool_contract.json"
UPDATE_FLAG = "UPDATE_TOOL_CONTRACT"

TOOLS = [BrightDataSERP, BrightDataUnlocker, BrightDataWebScraperAPI]


def _tool_contract(tool: BaseTool) -> Dict[str, Any]:
    fields = tool.get_input_schema().model_fields
    return {
        "name": tool.name,
        "args": list(fields),
        "required": [name for name, field in fields.items() if field.is_required()],
    }


def current_contract() -> Dict[str, Any]:
    tools = {cls.__name__: cls(bright_data_api_key="test-key") for cls in TOOLS}
    scraper_fields = tools["BrightDataWebScraperAPI"].get_input_schema().model_fields
    return {
        "tools": {name: _tool_contract(tool) for name, tool in tools.items()},
        "dataset_types": list(get_args(scraper_fields["dataset_type"].annotation)),
        "dataset_ids": dict(DATASET_MAPPING),
    }


def test_tool_contract_matches_snapshot() -> None:
    current = current_contract()

    if os.environ.get(UPDATE_FLAG) == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        with SNAPSHOT.open("w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(current, indent=2) + "\n")
        pytest.skip(f"{UPDATE_FLAG}=1: rewrote {SNAPSHOT.name}, review the diff")

    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    for name in sorted(set(expected["tools"]) | set(current["tools"])):
        assert current["tools"].get(name) == expected["tools"].get(name), f"tool {name}"
    assert current["dataset_types"] == expected["dataset_types"]
    # Known bug: youtube_videos has the same dataset id as booking_hotel_listings
    # (gd_m5mbdl081229ln6t4a). The snapshot records it as it is today; unit F4
    # fixes the id and updates the snapshot.
    assert current["dataset_ids"] == expected["dataset_ids"]
