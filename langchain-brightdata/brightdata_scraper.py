"""Tool for the Bright Data Dataset API."""

from typing import Any, Dict, List, Optional, Type, Union

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

from ._utilities import BrightDataWebScraperAPIWrapper


class BrightDataDatasetInput(BaseModel):
    """Input for BrightData's Dataset API."""
    
    url: str = Field(description="URL to extract structured data from")
    
    dataset_type: str = Field(
        description="""Type of dataset to use.
        
        Options include:
        - "amazon_product": Extract detailed Amazon product data
        - "amazon_product_reviews": Extract Amazon product reviews
        - "linkedin_person_profile": Extract LinkedIn person profile data
        - "linkedin_company_profile": Extract LinkedIn company profile data
        """
    )
    
    zipcode: Optional[str] = Field(
        default=None,
        description="""Optional zipcode for location-specific data.
        
        Useful for products or services with location-dependent pricing or availability.
        """
    )


class BrightDataWebScraperAPI(BaseTool):
    """Tool that uses Bright Data's Dataset API to extract structured data from websites.
    
    This tool allows you to extract structured data from various websites including 
    Amazon product details, LinkedIn profiles, and more.
    """

    name: str = "brightdata_dataset"
    description: str = (
        "Extract structured data from websites using Bright Data's Dataset API. "
        "Useful for getting detailed product information, social media profiles, and more. "
        "Options include amazon_product, amazon_product_reviews, linkedin_person_profile, "
        "and linkedin_company_profile. Input should be a URL and dataset type."
    )

    args_schema: Type[BaseModel] = BrightDataDatasetInput
    handle_tool_error: bool = True

    dataset_mapping: Dict[str, str] = {
        "amazon_product": "gd_l7q7dkf244hwjntr0",
        "amazon_product_reviews": "gd_le8e811kzy4ggddlq",
        "linkedin_person_profile": "gd_l1viktl72bvl7bjuj0",
        "linkedin_company_profile": "gd_l1vikfnt1wgvvqz95w"
    }

    api_wrapper: BrightDataWebScraperAPIWrapper = Field(default_factory=BrightDataWebScraperAPIWrapper)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the BrightDataDataset tool."""
        if "bright_data_api_key" in kwargs:
            kwargs["api_wrapper"] = BrightDataWebScraperAPIWrapper(
                bright_data_api_key=kwargs["bright_data_api_key"]
            )

        super().__init__(**kwargs)

    def _run(
        self,
        url: str,
        dataset_type: str,
        zipcode: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """Execute a structured data extraction using the Bright Data Dataset API."""
        try:
            if dataset_type not in self.dataset_mapping:
                raise ToolException(
                    f"Invalid dataset type: {dataset_type}. "
                    f"Available types: {', '.join(self.dataset_mapping.keys())}"
                )
                
            dataset_id = self.dataset_mapping[dataset_type]
            
            results = self.api_wrapper.get_dataset_data(
                dataset_id=dataset_id,
                url=url,
                zipcode=zipcode
            )
            
            if not results:
                raise ToolException(f"No data found for URL: {url}")
                
            return results

        except Exception as e:
            if isinstance(e, ToolException):
                raise e
            raise ToolException(f"Error extracting data from {url}: {e}")
