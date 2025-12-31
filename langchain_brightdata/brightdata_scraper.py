"""Tool for the Bright Data Dataset API."""

from typing import Any, Dict, List, Literal, Optional, Type

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

from ._utilities import BrightDataWebScraperAPIWrapper


DATASETS = [
    {
        "id": "amazon_product",
        "dataset_id": "gd_l7q7dkf244hwjntr0",
        "description": "Extract structured Amazon product data. Requires a valid product URL with /dp/ in it.",
        "inputs": ["url"],
    },
    {
        "id": "amazon_product_reviews",
        "dataset_id": "gd_le8e811kzy4ggddlq",
        "description": "Extract structured Amazon product review data. Requires a valid product URL with /dp/ in it.",
        "inputs": ["url"],
    },
    {
        "id": "amazon_product_search",
        "dataset_id": "gd_lwdb4vjm1ehb499uxs",
        "description": "Extract structured Amazon product search data. Requires a valid search keyword and Amazon domain URL.",
        "inputs": ["keyword", "url"],
        "fixed_values": {"pages_to_search": "1"},
    },
    {
        "id": "walmart_product",
        "dataset_id": "gd_l95fol7l1ru6rlo116",
        "description": "Extract structured Walmart product data. Requires a valid product URL with /ip/ in it.",
        "inputs": ["url"],
    },
    {
        "id": "walmart_seller",
        "dataset_id": "gd_m7ke48w81ocyu4hhz0",
        "description": "Extract structured Walmart seller data. Requires a valid Walmart seller URL.",
        "inputs": ["url"],
    },
    {
        "id": "ebay_product",
        "dataset_id": "gd_ltr9mjt81n0zzdk1fb",
        "description": "Extract structured eBay product data. Requires a valid eBay product URL.",
        "inputs": ["url"],
    },
    {
        "id": "homedepot_products",
        "dataset_id": "gd_lmusivh019i7g97q2n",
        "description": "Extract structured Home Depot product data. Requires a valid Home Depot product URL.",
        "inputs": ["url"],
    },
    {
        "id": "zara_products",
        "dataset_id": "gd_lct4vafw1tgx27d4o0",
        "description": "Extract structured Zara product data. Requires a valid Zara product URL.",
        "inputs": ["url"],
    },
    {
        "id": "etsy_products",
        "dataset_id": "gd_ltppk0jdv1jqz25mz",
        "description": "Extract structured Etsy product data. Requires a valid Etsy product URL.",
        "inputs": ["url"],
    },
    {
        "id": "bestbuy_products",
        "dataset_id": "gd_ltre1jqe1jfr7cccf",
        "description": "Extract structured Best Buy product data. Requires a valid Best Buy product URL.",
        "inputs": ["url"],
    },
    {
        "id": "linkedin_person_profile",
        "dataset_id": "gd_l1viktl72bvl7bjuj0",
        "description": "Extract structured LinkedIn person profile data. Requires a valid LinkedIn profile URL.",
        "inputs": ["url"],
    },
    {
        "id": "linkedin_company_profile",
        "dataset_id": "gd_l1vikfnt1wgvvqz95w",
        "description": "Extract structured LinkedIn company profile data. Requires a valid LinkedIn company URL.",
        "inputs": ["url"],
    },
    {
        "id": "linkedin_job_listings",
        "dataset_id": "gd_lpfll7v5hcqtkxl6l",
        "description": "Extract structured LinkedIn job listings data. Requires a valid LinkedIn job URL.",
        "inputs": ["url"],
    },
    {
        "id": "linkedin_posts",
        "dataset_id": "gd_lyy3tktm25m4avu764",
        "description": "Extract structured LinkedIn posts data. Requires a valid LinkedIn post URL.",
        "inputs": ["url"],
    },
    {
        "id": "linkedin_people_search",
        "dataset_id": "gd_m8d03he47z8nwb5xc",
        "description": "Extract structured LinkedIn people search data. Requires URL, first_name, and last_name.",
        "inputs": ["url", "first_name", "last_name"],
    },
    {
        "id": "crunchbase_company",
        "dataset_id": "gd_l1vijqt9jfj7olije",
        "description": "Extract structured Crunchbase company data. Requires a valid Crunchbase company URL.",
        "inputs": ["url"],
    },
    {
        "id": "zoominfo_company_profile",
        "dataset_id": "gd_m0ci4a4ivx3j5l6nx",
        "description": "Extract structured ZoomInfo company profile data. Requires a valid ZoomInfo company URL.",
        "inputs": ["url"],
    },
    {
        "id": "instagram_profiles",
        "dataset_id": "gd_l1vikfch901nx3by4",
        "description": "Extract structured Instagram profile data. Requires a valid Instagram profile URL.",
        "inputs": ["url"],
    },
    {
        "id": "instagram_posts",
        "dataset_id": "gd_lk5ns7kz21pck8jpis",
        "description": "Extract structured Instagram post data. Requires a valid Instagram post URL.",
        "inputs": ["url"],
    },
    {
        "id": "instagram_reels",
        "dataset_id": "gd_lyclm20il4r5helnj",
        "description": "Extract structured Instagram reel data. Requires a valid Instagram reel URL.",
        "inputs": ["url"],
    },
    {
        "id": "instagram_comments",
        "dataset_id": "gd_ltppn085pokosxh13",
        "description": "Extract structured Instagram comments data. Requires a valid Instagram post URL.",
        "inputs": ["url"],
    },
    {
        "id": "facebook_posts",
        "dataset_id": "gd_lyclm1571iy3mv57zw",
        "description": "Extract structured Facebook post data. Requires a valid Facebook post URL.",
        "inputs": ["url"],
    },
    {
        "id": "facebook_marketplace_listings",
        "dataset_id": "gd_lvt9iwuh6fbcwmx1a",
        "description": "Extract structured Facebook marketplace listing data. Requires a valid Facebook marketplace URL.",
        "inputs": ["url"],
    },
    {
        "id": "facebook_company_reviews",
        "dataset_id": "gd_m0dtqpiu1mbcyc2g86",
        "description": "Extract structured Facebook company reviews. Requires a valid Facebook company URL and num_of_reviews.",
        "inputs": ["url", "num_of_reviews"],
    },
    {
        "id": "facebook_events",
        "dataset_id": "gd_m14sd0to1jz48ppm51",
        "description": "Extract structured Facebook events data. Requires a valid Facebook event URL.",
        "inputs": ["url"],
    },
    {
        "id": "tiktok_profiles",
        "dataset_id": "gd_l1villgoiiidt09ci",
        "description": "Extract structured TikTok profile data. Requires a valid TikTok profile URL.",
        "inputs": ["url"],
    },
    {
        "id": "tiktok_posts",
        "dataset_id": "gd_lu702nij2f790tmv9h",
        "description": "Extract structured TikTok post data. Requires a valid TikTok post URL.",
        "inputs": ["url"],
    },
    {
        "id": "tiktok_shop",
        "dataset_id": "gd_m45m1u911dsa4274pi",
        "description": "Extract structured TikTok shop data. Requires a valid TikTok shop product URL.",
        "inputs": ["url"],
    },
    {
        "id": "tiktok_comments",
        "dataset_id": "gd_lkf2st302ap89utw5k",
        "description": "Extract structured TikTok comments data. Requires a valid TikTok video URL.",
        "inputs": ["url"],
    },
    {
        "id": "google_maps_reviews",
        "dataset_id": "gd_luzfs1dn2oa0teb81",
        "description": "Extract structured Google Maps reviews data. Requires a valid Google Maps URL.",
        "inputs": ["url", "days_limit"],
        "defaults": {"days_limit": "3"},
    },
    {
        "id": "google_shopping",
        "dataset_id": "gd_ltppk50q18kdw67omz",
        "description": "Extract structured Google Shopping data. Requires a valid Google Shopping product URL.",
        "inputs": ["url"],
    },
    {
        "id": "google_play_store",
        "dataset_id": "gd_lsk382l8xei8vzm4u",
        "description": "Extract structured Google Play Store app data. Requires a valid Google Play Store app URL.",
        "inputs": ["url"],
    },
    {
        "id": "apple_app_store",
        "dataset_id": "gd_lsk9ki3u2iishmwrui",
        "description": "Extract structured Apple App Store app data. Requires a valid Apple App Store app URL.",
        "inputs": ["url"],
    },
    {
        "id": "reuter_news",
        "dataset_id": "gd_lyptx9h74wtlvpnfu",
        "description": "Extract structured Reuters news data. Requires a valid Reuters news article URL.",
        "inputs": ["url"],
    },
    {
        "id": "github_repository_file",
        "dataset_id": "gd_lyrexgxc24b3d4imjt",
        "description": "Extract structured GitHub repository file data. Requires a valid GitHub file URL.",
        "inputs": ["url"],
    },
    {
        "id": "yahoo_finance_business",
        "dataset_id": "gd_lmrpz3vxmz972ghd7",
        "description": "Extract structured Yahoo Finance business data. Requires a valid Yahoo Finance business URL.",
        "inputs": ["url"],
    },
    {
        "id": "x_posts",
        "dataset_id": "gd_lwxkxvnf1cynvib9co",
        "description": "Extract structured X (Twitter) post data. Requires a valid X post URL.",
        "inputs": ["url"],
    },
    {
        "id": "zillow_properties_listing",
        "dataset_id": "gd_lfqkr8wm13ixtbd8f5",
        "description": "Extract structured Zillow properties listing data. Requires a valid Zillow listing URL.",
        "inputs": ["url"],
    },
    {
        "id": "booking_hotel_listings",
        "dataset_id": "gd_m5mbdl081229ln6t4a",
        "description": "Extract structured Booking.com hotel listings data. Requires a valid Booking.com hotel URL.",
        "inputs": ["url"],
    },
    {
        "id": "youtube_profiles",
        "dataset_id": "gd_lk538t2k2p1k3oos71",
        "description": "Extract structured YouTube channel profile data. Requires a valid YouTube channel URL.",
        "inputs": ["url"],
    },
    {
        "id": "youtube_videos",
        "dataset_id": "gd_m5mbdl081229ln6t4a",
        "description": "Extract structured YouTube video data. Requires a valid YouTube video URL.",
        "inputs": ["url"],
    },
    {
        "id": "youtube_comments",
        "dataset_id": "gd_lk9q0ew71spt1mxywf",
        "description": "Extract structured YouTube comments data. Requires a valid YouTube video URL.",
        "inputs": ["url", "num_of_comments"],
        "defaults": {"num_of_comments": "10"},
    },
    {
        "id": "reddit_posts",
        "dataset_id": "gd_lvz8ah06191smkebj4",
        "description": "Extract structured Reddit post data. Requires a valid Reddit post URL.",
        "inputs": ["url"],
    },
]

DATASET_MAPPING = {d["id"]: d["dataset_id"] for d in DATASETS}
DATASET_INPUTS = {d["id"]: d["inputs"] for d in DATASETS}
DATASET_DEFAULTS = {d["id"]: d.get("defaults", {}) for d in DATASETS}
DATASET_FIXED_VALUES = {d["id"]: d.get("fixed_values", {}) for d in DATASETS}
DATASET_DESCRIPTIONS = {d["id"]: d["description"] for d in DATASETS}

DatasetType = Literal[
    "amazon_product", "amazon_product_reviews", "amazon_product_search",
    "walmart_product", "walmart_seller", "ebay_product", "homedepot_products",
    "zara_products", "etsy_products", "bestbuy_products",
    "linkedin_person_profile", "linkedin_company_profile", "linkedin_job_listings",
    "linkedin_posts", "linkedin_people_search",
    "crunchbase_company", "zoominfo_company_profile",
    "instagram_profiles", "instagram_posts", "instagram_reels", "instagram_comments",
    "facebook_posts", "facebook_marketplace_listings", "facebook_company_reviews", "facebook_events",
    "tiktok_profiles", "tiktok_posts", "tiktok_shop", "tiktok_comments",
    "google_maps_reviews", "google_shopping", "google_play_store",
    "youtube_profiles", "youtube_videos", "youtube_comments",
    "apple_app_store", "reuter_news", "github_repository_file", "yahoo_finance_business",
    "x_posts", "zillow_properties_listing", "booking_hotel_listings", "reddit_posts",
]


class BrightDataDatasetInput(BaseModel):
    """Input for BrightData's Dataset API to extract structured data from websites."""

    dataset_type: DatasetType = Field(
        description=(
            "Type of dataset to extract. Choose based on the website:\n"
            "- E-commerce: amazon_product, amazon_product_reviews, amazon_product_search, "
            "walmart_product, walmart_seller, ebay_product, homedepot_products, zara_products, etsy_products, bestbuy_products\n"
            "- LinkedIn: linkedin_person_profile, linkedin_company_profile, linkedin_job_listings, linkedin_posts, linkedin_people_search\n"
            "- Business: crunchbase_company, zoominfo_company_profile\n"
            "- Instagram: instagram_profiles, instagram_posts, instagram_reels, instagram_comments\n"
            "- Facebook: facebook_posts, facebook_marketplace_listings, facebook_company_reviews, facebook_events\n"
            "- TikTok: tiktok_profiles, tiktok_posts, tiktok_shop, tiktok_comments\n"
            "- Google: google_maps_reviews, google_shopping, google_play_store\n"
            "- YouTube: youtube_profiles, youtube_videos, youtube_comments\n"
            "- Other: apple_app_store, reuter_news, github_repository_file, yahoo_finance_business, "
            "x_posts, zillow_properties_listing, booking_hotel_listings, reddit_posts"
        )
    )

    url: Optional[str] = Field(
        default=None,
        description="URL to extract data from. Required for most datasets. Must be a valid URL for the chosen platform."
    )

    keyword: Optional[str] = Field(
        default=None,
        description="Search keyword. Required only for amazon_product_search."
    )

    first_name: Optional[str] = Field(
        default=None,
        description="First name. Required only for linkedin_people_search."
    )

    last_name: Optional[str] = Field(
        default=None,
        description="Last name. Required only for linkedin_people_search."
    )

    num_of_reviews: Optional[str] = Field(
        default=None,
        description="Number of reviews to fetch. Required for facebook_company_reviews."
    )

    num_of_comments: Optional[str] = Field(
        default=None,
        description="Number of comments to fetch. Used by youtube_comments (default: 10)."
    )

    days_limit: Optional[str] = Field(
        default=None,
        description="Number of days to limit results. Used by google_maps_reviews (default: 3)."
    )

    zipcode: Optional[str] = Field(
        default=None,
        description="Zipcode for location-specific data (e.g., for Amazon products with regional pricing)."
    )


class BrightDataWebScraperAPI(BaseTool):
    """Tool to extract structured data from 45+ websites using Bright Data's Dataset API.

    Supports:
    - E-commerce: Amazon, Walmart, eBay, Home Depot, Zara, Etsy, Best Buy
    - Social: LinkedIn, Instagram, Facebook, TikTok, YouTube, X (Twitter), Reddit
    - Business: Crunchbase, ZoomInfo
    - Other: Google Maps, GitHub, Yahoo Finance, Zillow, Booking.com, App Stores
    """

    name: str = "brightdata_web_scraper"
    description: str = (
        "Extract structured data from 45+ websites. Use 'dataset_type' to specify the data source "
        "(e.g., 'amazon_product' for Amazon products, 'linkedin_person_profile' for LinkedIn profiles). "
        "Most datasets only require 'url'. Special cases: amazon_product_search needs 'keyword', "
        "linkedin_people_search needs 'first_name' and 'last_name', facebook_company_reviews needs 'num_of_reviews'."
    )

    args_schema: Type[BaseModel] = BrightDataDatasetInput
    handle_tool_error: bool = True

    api_wrapper: BrightDataWebScraperAPIWrapper = Field(default_factory=BrightDataWebScraperAPIWrapper)

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the BrightDataWebScraperAPI tool."""
        if "bright_data_api_key" in kwargs:
            kwargs["api_wrapper"] = BrightDataWebScraperAPIWrapper(
                bright_data_api_key=kwargs["bright_data_api_key"]
            )

        super().__init__(**kwargs)

    @staticmethod
    def get_supported_datasets() -> List[Dict[str, Any]]:
        """Return list of all supported datasets with their metadata."""
        return DATASETS.copy()

    @staticmethod
    def get_dataset_info(dataset_type: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific dataset type."""
        for d in DATASETS:
            if d["id"] == dataset_type:
                return d.copy()
        return None

    def _run(
        self,
        dataset_type: str,
        url: Optional[str] = None,
        keyword: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        num_of_reviews: Optional[str] = None,
        num_of_comments: Optional[str] = None,
        days_limit: Optional[str] = None,
        zipcode: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """Execute a structured data extraction using the Bright Data Dataset API."""
        try:
            if dataset_type not in DATASET_MAPPING:
                raise ToolException(
                    f"Invalid dataset type: {dataset_type}. "
                    f"Available types: {', '.join(DATASET_MAPPING.keys())}"
                )

            dataset_id = DATASET_MAPPING[dataset_type]
            required_inputs = DATASET_INPUTS[dataset_type]
            defaults = DATASET_DEFAULTS[dataset_type]
            fixed_values = DATASET_FIXED_VALUES[dataset_type]

            provided_params = {
                "url": url,
                "keyword": keyword,
                "first_name": first_name,
                "last_name": last_name,
                "num_of_reviews": num_of_reviews,
                "num_of_comments": num_of_comments,
                "days_limit": days_limit,
            }

            additional_params = {}

            for input_name in required_inputs:
                if input_name == "url":
                    continue  

                value = provided_params.get(input_name)
                if value is None:
                    if input_name in defaults:
                        value = defaults[input_name]
                    else:
                        raise ToolException(
                            f"Missing required parameter '{input_name}' for dataset type '{dataset_type}'. "
                            f"Required inputs: {required_inputs}"
                        )
                additional_params[input_name] = value

            additional_params.update(fixed_values)

            if "url" in required_inputs and not url:
                raise ToolException(
                    f"URL is required for dataset type '{dataset_type}'."
                )

            results = self.api_wrapper.get_dataset_data(
                dataset_id=dataset_id,
                url=url or "",
                zipcode=zipcode,
                additional_params=additional_params if additional_params else None
            )

            if not results:
                raise ToolException(f"No data found for the provided inputs.")

            return results

        except Exception as e:
            if isinstance(e, ToolException):
                raise e
            raise ToolException(f"Error extracting data: {e}")
