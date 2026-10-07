"""LangChain standard unit tests (langchain-tests ToolsUnitTests) for each tool."""

from typing import Any, Dict, Tuple, Type

from langchain_tests.unit_tests import ToolsUnitTests

from langchain_brightdata import (
    BrightDataSERP,
    BrightDataSERPAPIWrapper,
    BrightDataUnlocker,
    BrightDataUnlockerAPIWrapper,
    BrightDataWebScraperAPI,
    BrightDataWebScraperAPIWrapper,
)

API_KEY = "test-key"
ENV = {"BRIGHT_DATA_API_KEY": API_KEY}


# The key lives on tool.api_wrapper, so init_from_env_params compares the whole
# wrapper (pydantic compares SecretStr by its value).


class TestBrightDataSERPStandard(ToolsUnitTests):
    @property
    def tool_constructor(self) -> Type[BrightDataSERP]:
        return BrightDataSERP

    @property
    def tool_constructor_params(self) -> Dict[str, Any]:
        return {"bright_data_api_key": API_KEY}

    @property
    def tool_invoke_params_example(self) -> Dict[str, Any]:
        return {"query": "python programming language"}

    @property
    def init_from_env_params(self) -> Tuple[Dict[str, str], Dict[str, Any], Dict[str, Any]]:
        return ENV, {}, {"api_wrapper": BrightDataSERPAPIWrapper(bright_data_api_key=API_KEY)}


class TestBrightDataUnlockerStandard(ToolsUnitTests):
    @property
    def tool_constructor(self) -> Type[BrightDataUnlocker]:
        return BrightDataUnlocker

    @property
    def tool_constructor_params(self) -> Dict[str, Any]:
        return {"bright_data_api_key": API_KEY}

    @property
    def tool_invoke_params_example(self) -> Dict[str, Any]:
        return {"url": "https://books.toscrape.com/"}

    @property
    def init_from_env_params(self) -> Tuple[Dict[str, str], Dict[str, Any], Dict[str, Any]]:
        return ENV, {}, {"api_wrapper": BrightDataUnlockerAPIWrapper(bright_data_api_key=API_KEY)}


class TestBrightDataWebScraperAPIStandard(ToolsUnitTests):
    @property
    def tool_constructor(self) -> Type[BrightDataWebScraperAPI]:
        return BrightDataWebScraperAPI

    @property
    def tool_constructor_params(self) -> Dict[str, Any]:
        return {"bright_data_api_key": API_KEY}

    @property
    def tool_invoke_params_example(self) -> Dict[str, Any]:
        return {"dataset_type": "amazon_product", "url": "https://www.amazon.com/dp/B0863TXGM3"}

    @property
    def init_from_env_params(self) -> Tuple[Dict[str, str], Dict[str, Any], Dict[str, Any]]:
        return (
            ENV,
            {},
            {"api_wrapper": BrightDataWebScraperAPIWrapper(bright_data_api_key=API_KEY)},
        )
