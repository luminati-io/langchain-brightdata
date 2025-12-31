"""Tool for the Bright Data Web Unlocker."""

from typing import Any, Dict, List, Literal, Optional, Type

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

from ._utilities import BrightDataUnlockerAPIWrapper


class BrightDataUnlockerInput(BaseModel):
    """Input for BrightData's Web Unlocker."""
    
    url: str = Field(description="URL to access with the Bright Data Web Unlocker")
    
    format: Optional[Literal["raw"]] = Field(
        default="raw",
        description="Format of the response content (raw is standard)"
    )
    
    country: Optional[str] = Field(
        default=None,
        description="""Two-letter country code for geo-specific access.
        
        Set this when you need to view the website as if accessing from a specific country.
        Example values: "us", "gb", "de", "jp", etc.
        
        Leave as None to use default country routing.
        """
    )
    
    zone: Optional[str] = Field(
        default="unlocker",
        description="""Bright Data zone to use for the request.
        
        The "unlocker" zone is optimized for accessing websites that might block regular requests.
        
        Default is "unlocker".
        """
    )
    
    data_format: Optional[Literal["html", "markdown", "screenshot"]] = Field(
        default=None,
        description="""Output format for the retrieved content.
        
        "html" - Returns the standard HTML content (default)
        "markdown" - Returns content converted to markdown format (useful for LLM training)
        "screenshot" - Returns a PNG screenshot of the rendered page
        
        Leave as None to use the default HTML format.
        """
    )
    


class BrightDataUnlocker(BaseTool):
    """Tool that uses Bright Data's Web Unlocker to access websites.
    
    This tool allows you to access websites that may be protected by anti-bot measures,
    geo-restrictions, or other access limitations.
    """

    name: str = "brightdata_Unlocker"
    description: str = (
        "Access websites that might be geo-restricted or protected by anti-bot measures. "
        "Useful for retrieving content from websites that would normally block access. "
        "Returns page content, which can be in HTML, markdown, or screenshot format. "
        "Input should be a URL to access along with optional parameters for country, format, etc."
    )

    args_schema: Type[BaseModel] = BrightDataUnlockerInput
    handle_tool_error: bool = True

    format: Optional[Literal["raw"]] = "raw"
    country: Optional[str] = None
    zone: str = "unlocker"
    data_format: Optional[Literal["html", "markdown", "screenshot"]] = None

    api_wrapper: BrightDataUnlockerAPIWrapper = Field(default_factory=BrightDataUnlockerAPIWrapper)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the BrightDataUnlocker tool."""
        if "bright_data_api_key" in kwargs:
            kwargs["api_wrapper"] = BrightDataUnlockerAPIWrapper(
                bright_data_api_key=kwargs["bright_data_api_key"]
            )

        super().__init__(**kwargs)

    def _run(
        self,
        url: str,
        format: Optional[Literal["raw"]] = None,
        country: Optional[str] = None,
        zone: Optional[str] = None,
        data_format: Optional[Literal["html", "markdown", "screenshot"]] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """Execute a web access request using the Bright Data Web Unlocker."""
        try:
            format_to_use = format if format is not None else self.format
            country_to_use = country if country is not None else self.country
            zone_to_use = zone if zone is not None else self.zone
            data_format_to_use = data_format if data_format is not None else self.data_format

            results = self.api_wrapper.get_page_content(
                url=url,
                format=format_to_use,
                country=country_to_use,
                zone=zone_to_use,
                data_format=data_format_to_use,
            )

            if not results:
                raise ToolException(
                    f"No content returned from URL {url}. The site may be unavailable."
                )

            return results
        except Exception as e:
            if isinstance(e, ToolException):
                raise e
            raise ToolException(f"Error accessing URL {url}: {e}")