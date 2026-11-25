"""Tool that reads a web page through the Bright Data Fetch API."""

from typing import Any, Literal, Optional, Type

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

from ._utilities import BrightDataWebFetchAPIWrapper

PageFormat = Literal["markdown", "text", "html"]


class BrightDataWebFetchInput(BaseModel):
    """Input for BrightDataWebFetch."""

    url: str = Field(description="The full URL of the page to read, starting with https://")

    format: Optional[PageFormat] = Field(
        default=None,
        description=(
            'How to return the page: "markdown" (default, best for reading), '
            '"text" (plain text) or "html" (the page source).'
        ),
    )


class BrightDataWebFetch(BaseTool):
    """Read one web page and return its content.

    Uses the Bright Data Fetch API, which gets past bot protection and needs only
    an API key. No zone is used or created.

    Setup:
        Set the ``BRIGHT_DATA_API_KEY`` environment variable, or pass
        ``bright_data_api_key`` when creating the tool.

    Example:
        .. code-block:: python

            from langchain_brightdata import BrightDataWebFetch

            tool = BrightDataWebFetch()
            tool.invoke({"url": "https://example.com"})
    """

    name: str = "brightdata_web_fetch"
    description: str = (
        "Read one web page and return its content as markdown, including pages that block "
        "ordinary requests. Use it when you have a URL and need what the page says. "
        "Input is the page URL."
    )

    args_schema: Type[BaseModel] = BrightDataWebFetchInput
    handle_tool_error: bool = True

    format: PageFormat = "markdown"

    api_wrapper: BrightDataWebFetchAPIWrapper = Field(default_factory=BrightDataWebFetchAPIWrapper)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the BrightDataWebFetch tool."""
        if "bright_data_api_key" in kwargs:
            kwargs["api_wrapper"] = BrightDataWebFetchAPIWrapper(
                bright_data_api_key=kwargs["bright_data_api_key"]
            )

        super().__init__(**kwargs)

    def _run(
        self,
        url: str,
        format: Optional[PageFormat] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Read the page at `url`."""
        try:
            return self.api_wrapper.fetch_page(url, format=format or self.format)
        except Exception as e:
            raise ToolException(str(e)) from e
