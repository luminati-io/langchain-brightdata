"""Utility for Bright Data API interactions."""
import json
import time
from typing import Any, Dict, List, Literal, Optional
import aiohttp
import requests
from langchain_core.utils import get_from_dict_or_env
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator
import urllib.parse

BRIGHTDATA_API_URL = "https://api.brightdata.com"

class BrightDataAPIWrapper(BaseModel):
    """Base wrapper for Bright Data API."""
    bright_data_api_key: SecretStr

    model_config = ConfigDict(
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key exists in environment."""
        bright_data_api_key = get_from_dict_or_env(
            values, "bright_data_api_key", "BRIGHT_DATA_API_KEY"
        )
        values["bright_data_api_key"] = bright_data_api_key
        return values

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.bright_data_api_key.get_secret_value()}",
            "Content-Type": "application/json"
        }

class BrightDataUnlockerAPIWrapper(BrightDataAPIWrapper):
    """Wrapper for Bright Data Web Unlocker API.
    
    This wrapper can be used with various Bright Data zones, including "Unlocker",
    "scraper", and other API-accessible services.
    """

    def get_page_content(
        self,
        url: str,
        zone: str = "unlocker",
        format: Optional[Literal["raw"]] = "raw",
        country: Optional[str] = None,
        data_format: Optional[Literal["html", "markdown", "screenshot"]] = None,
    ) -> Dict:
        """Get content from a web page using Bright Data Web Unlocker.
        
        Args:
            url: URL to access
            zone: Bright Data zone (default "unlocker")
            format: Response format ("raw" is standard)
            country: Two-letter country code for geo-targeting (e.g., "us", "gb")
            data_format: Content format type (html, markdown, screenshot)
            disable_captcha: Whether to disable automatic CAPTCHA solving
            custom_headers: Custom HTTP headers to send with the request
            custom_cookies: Custom cookies to send with the request
            expect_elements: Elements to wait for before returning the page
            user_agent_type: Type of user agent to use (desktop or mobile)
            
        Returns:
            Dictionary containing the response data
        """
        params = {
            "zone": zone,
            "url": url,
            "format": format
        }
        
        if country:
            params["country"] = country
        if data_format:
            params["data_format"] = data_format
        
        params = {k: v for k, v in params.items() if v is not None}

        response = requests.post(
            f"{BRIGHTDATA_API_URL}/request",
            json=params,
            headers=self._get_headers(),
        )
        
        return response.text
    

class BrightDataSERPAPIWrapper(BrightDataAPIWrapper):
    """Wrapper for Bright Data SERP API."""

    def get_search_results(
        self,
        query: str,
        zone: Optional[str] = "serp",
        search_engine: Optional[str] = "google",
        country: Optional[str] = "us",
        language: Optional[str] = "en",
        results_count: Optional[int] = 10,
        search_type: Optional[str] = None,
        device_type: Optional[str] = None,
        parse_results: Optional[bool] = False,
    ) -> Dict:
        """Get search results using Bright Data SERP API.
        
        Args:
            query: Search query
            search_engine: Search engine to use (default "google")
            country: Two-letter country code for geo-targeting (e.g., "us", "gb")
            language: Two-letter language code (e.g., "en", "es")
            results_count: Number of results to return
            search_type: Type of search (e.g., "shop", "news", "images")
            device_type: Device type to simulate ("desktop" (Deafult) or "mobile")
            parse_results: Whether to return parsed JSON results
            
        Returns:
            Dictionary containing the search results
        """
        query = urllib.parse.quote(query)
        url = f"https://www.{search_engine}.com/search?q={query}"
        
        params = []
        
        if country:
            params.append(f"gl={country}")
        
        if language:
            params.append(f"hl={language}")
        
        if results_count:
            params.append(f"num={results_count}")
        
        if parse_results:
            params.append(f"brd_json=1")

        if search_type:
            if search_type == "jobs":
                params.append("ibp=htl;jobs")
            else:
                params.append(f"tbm={search_type}")
        if device_type:
            if device_type == "mobile":
                params.append("brd_mobile=1")
            elif device_type == "ios":
                params.append("brd_mobile=ios")
            elif device_type == "android":
                params.append("brd_mobile=android")
        
        if params:
            url += "&" + "&".join(params)
        
        request_params = {
            "zone": zone,
            "url": url,
            "format": "raw",
        }
        
        request_params = {k: v for k, v in request_params.items() if v is not None}

        response = requests.post(
            f"{BRIGHTDATA_API_URL}/request",
            json=request_params,
            headers=self._get_headers(),
        )

        return response.text


class BrightDataWebScraperAPIWrapper(BrightDataAPIWrapper):
    """Wrapper for Bright Data Dataset API.
    
    This wrapper can be used to access Bright Data's structured datasets,
    including product data, social media profiles, and more.
    """

    def get_dataset_data(
        self,
        dataset_id: str,
        url: Optional[str] = None,
        zipcode: Optional[str] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        max_poll_attempts: int = 60,
        poll_interval: int = 1,
    ) -> Dict:
        """Get structured data from a Bright Data Dataset.

        Args:
            dataset_id: The ID of the Bright Data Dataset to query
            url: URL to extract data from (required for most datasets)
            zipcode: Optional zipcode for location-specific data
            additional_params: Any additional parameters to include in the request
            max_poll_attempts: Maximum number of polling attempts (default: 60)
            poll_interval: Seconds to wait between polls (default: 10)

        Returns:
            Dictionary containing the extracted structured data
        """
        request_data = {}

        if url:
            request_data["url"] = url

        if zipcode:
            request_data["zipcode"] = zipcode

        if additional_params:
            filtered_params = {k: v for k, v in additional_params.items() if v is not None and v != ""}
            request_data.update(filtered_params)

        response = requests.post(
            f"{BRIGHTDATA_API_URL}/datasets/v3/scrape",
            params={"dataset_id": dataset_id, "include_errors": "true"},
            json=[request_data],
            headers=self._get_headers(),
        )

        if response.status_code == 200:
            return response.text

        if response.status_code == 202:
            response_data = response.json()
            snapshot_id = response_data.get("snapshot_id")

            if not snapshot_id:
                raise ValueError(f"No snapshot_id in 202 response: {response.text}")

            for attempt in range(max_poll_attempts):
                time.sleep(poll_interval)

                snapshot_response = requests.get(
                    f"{BRIGHTDATA_API_URL}/datasets/v3/snapshot/{snapshot_id}",
                    params={"format": "json"},
                    headers=self._get_headers(),
                )

                if snapshot_response.status_code == 200:
                    return snapshot_response.text

                if snapshot_response.status_code == 202:
                    status_data = snapshot_response.json()
                    status = status_data.get("status", "")
                    if status in ["running", "building", "starting"]:
                        continue
                    continue

                raise ValueError(
                    f"Unexpected status {snapshot_response.status_code} while polling: {snapshot_response.text}"
                )

            raise ValueError(f"Timeout after {max_poll_attempts * poll_interval} seconds waiting for data")

        error_message = f"Error {response.status_code}: {response.text}"
        raise ValueError(error_message)
    
    async def get_dataset_data_async(
        self,
        dataset_id: str,
        url: Optional[str] = None,
        zipcode: Optional[str] = None,
        additional_params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Get structured data from a Bright Data Dataset asynchronously.

        Args:
            dataset_id: The ID of the Bright Data Dataset to query
            url: URL to extract data from (required for most datasets)
            zipcode: Optional zipcode for location-specific data
            additional_params: Any additional parameters to include in the request

        Returns:
            Dictionary containing the extracted structured data
        """
        request_data = {}

        if url:
            request_data["url"] = url

        if zipcode:
            request_data["zipcode"] = zipcode

        if additional_params:
            filtered_params = {k: v for k, v in additional_params.items() if v is not None and v != ""}
            request_data.update(filtered_params)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BRIGHTDATA_API_URL}/datasets/v3/trigger",
                params={"dataset_id": dataset_id, "include_errors": "true"},
                json=[request_data],
                headers=self._get_headers()
            ) as response:
                return response