from typing import Any, Dict, List, Literal, Optional, Type

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

from ._utilities import BrightDataSERPAPIWrapper

class BrightDataSERPInput(BaseModel):
    """Input for BrightData's SERP API."""

    query: str = Field(description="Search query to perform with the SERP API")

    zone: Optional[str] = Field(
        default=None,
        description="""Bright Data SERP API zone name.

        This should match the zone name configured in your Bright Data account.
        Default is "serp".
        """
    )

    search_engine: Optional[str] = Field(
        default="google",
        description="""Search engine to use for the query.
        
        Default is "google". Other options include "bing", "yahoo", etc.
        """
    )
    
    country: Optional[str] = Field(
        default="us",
        description="""Two-letter country code for localized search results.
        
        Examples: "us", "gb", "de", "jp", etc.
        
        Default is "us".
        """
    )
    
    language: Optional[str] = Field(
        default="en",
        description="""Two-letter language code for the search results.
        
        Examples: "en", "es", "fr", "de", etc.
        
        Default is "en".
        """
    )
    
    results_count: Optional[int] = Field(
        default=10,
        description="""Number of search results to return.
        
        Default is 10. Maximum value is typically 100.
        """
    )
    
    search_type: Optional[str] = Field(
        default=None,
        description="""Type of search to perform.
        
        Options include:
        - None (default): Regular web search
        - "isch": Images search
        - "shop": Shopping search
        - "nws": News search
        - "jobs": Jobs search
        """
    )
    
    device_type: Optional[str] = Field(
        default=None,
        description="""Device type to simulate for the search.
        
        Options include:
        - None (default): Desktop device
        - "mobile": Generic mobile device
        - "ios": iOS device (iPhone)
        - "android": Android device
        """
    )
    
    parse_results: Optional[bool] = Field(
        default=True,
        description="""Whether to return parsed JSON results.
        
        Default is True, which returns structured JSON.
        Set to False to get raw HTML response.
        """
    )

class BrightDataSERP(BaseTool):
    """Tool that uses Bright Data's SERP API to perform search engine queries.
    
    This tool allows you to search the web and get results from various search engines,
    with options for geo-targeting, language, device type, and search type.
    """

    name: str = "brightdata_serp"
    description: str = (
        "Perform search engine queries with geo-targeting and customization options. "
        "Useful for finding information on the web from specific countries or languages. "
        "Returns search engine results, which can be filtered by type (web, news, images, shopping). "
        "Input should be a search query along with optional parameters."
    )

    args_schema: Type[BaseModel] = BrightDataSERPInput
    handle_tool_error: bool = True

    zone: str = "serp"
    search_engine: str = "google"
    country: str = "us"
    language: str = "en"
    results_count: Optional[int] = 10
    search_type: Optional[str] = None
    device_type: Optional[str] = None
    parse_results: bool = False

    api_wrapper: BrightDataSERPAPIWrapper = Field(default_factory=BrightDataSERPAPIWrapper)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the BrightDataSERP tool."""
        if "bright_data_api_key" in kwargs:
            kwargs["api_wrapper"] = BrightDataSERPAPIWrapper(
                bright_data_api_key=kwargs["bright_data_api_key"]
            )

        super().__init__(**kwargs)

    def _run(
        self,
        query: str,
        zone: Optional[str] = None,
        search_engine: Optional[str] = "google",
        country: Optional[str] = None,
        language: Optional[str] = None,
        results_count: Optional[int] = None,
        search_type: Optional[str] = None,
        device_type: Optional[str] = None,
        parse_results: Optional[bool] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """Execute a search query using the Bright Data SERP API."""
        try:
            zone_to_use = zone if zone is not None else self.zone
            search_engine_to_use = search_engine if search_engine is not None else self.search_engine
            country_to_use = country if country is not None else self.country
            language_to_use = language if language is not None else self.language
            results_count_to_use = results_count if results_count is not None else self.results_count
            search_type_to_use = search_type if search_type is not None else self.search_type
            device_type_to_use = device_type if device_type is not None else self.device_type
            parse_results_to_use = parse_results if parse_results is not None else self.parse_results

            results = self.api_wrapper.get_search_results(
                query=query,
                zone=zone_to_use,
                search_engine=search_engine_to_use,
                country=country_to_use,
                language=language_to_use,
                results_count=results_count_to_use,
                search_type=search_type_to_use,
                device_type=device_type_to_use,
                parse_results=parse_results_to_use,
            )

            if not results or (isinstance(results, dict) and not results.get("results") and not results.get("content")):

                error_message = (
                    f"No search results found for '{query}'. "
                    f"Try modifying your search parameters."
                )
                raise ToolException(error_message)

            return results
        except Exception as e:
            if isinstance(e, ToolException):
                raise e
            raise ToolException(f"Error performing search for '{query}': {e}")
