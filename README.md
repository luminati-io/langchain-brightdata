<div align="center">

# langchain-brightdata

**LangChain integration for Bright Data's web data APIs**

[![PyPI version](https://img.shields.io/pypi/v/langchain-brightdata?color=blue)](https://pypi.org/project/langchain-brightdata/)
[![Python](https://img.shields.io/pypi/pyversions/langchain-brightdata)](https://pypi.org/project/langchain-brightdata/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Downloads](https://img.shields.io/pypi/dm/langchain-brightdata)](https://pypi.org/project/langchain-brightdata/)

[Installation](#installation) •
[Quick Start](#quick-start) •
[Tools](#tools) •
[Configuration](#configuration) •
[Resources](#resources)

</div>

---

## Overview

**langchain-brightdata** provides LangChain tools for [Bright Data](https://brightdata.com)'s web data APIs, enabling your AI agents to:

- **Search** - Query search engines with geo-targeting and language customization
- **Unlock** - Access geo-restricted or bot-protected websites
- **Scrape** - Extract structured data from Amazon, LinkedIn, and 100+ domains

---

## Installation

```bash
pip install langchain-brightdata
```

**Requirements:** Python 3.9+

---

## Quick Start

### 1. Get your API key

Sign up at [Bright Data](https://brightdata.com) and get your API key from the dashboard.

### 2. Set up authentication

```python
import os
os.environ["BRIGHT_DATA_API_KEY"] = "your-api-key"
```

Or pass it directly:

```python
from langchain_brightdata import BrightDataSERP
tool = BrightDataSERP(bright_data_api_key="your-api-key")
```

### 3. Use with LangChain agents

```python
from langchain_brightdata import BrightDataSERP, BrightDataUnlocker, BrightDataWebScraperAPI
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI

# Initialize tools
tools = [
    BrightDataSERP(),
    BrightDataUnlocker(),
    BrightDataWebScraperAPI()
]

# Create agent
llm = ChatOpenAI(model="gpt-4")
agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS)

# Run
agent.run("Search for the latest AI news and summarize the top result")
```

---

## Tools

### BrightDataSERP

Search engine results with geo-targeting and customization.

```python
from langchain_brightdata import BrightDataSERP

serp = BrightDataSERP()

# Simple search
results = serp.invoke("latest AI research")

# Advanced search
results = serp.invoke({
    "query": "electric vehicles",
    "country": "de",
    "language": "de",
    "search_type": "news",
    "results_count": 20
})
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | Search query |
| `zone` | str | `"serp"` | Bright Data zone name |
| `search_engine` | str | `"google"` | Search engine (`google`, `bing`, `yahoo`) |
| `country` | str | `"us"` | Two-letter country code |
| `language` | str | `"en"` | Two-letter language code |
| `results_count` | int | `10` | Number of results (max 100) |
| `search_type` | str | `None` | `None` (web), `"isch"` (images), `"shop"`, `"nws"` (news), `"jobs"` |
| `device_type` | str | `None` | `None` (desktop), `"mobile"`, `"ios"`, `"android"` |
| `parse_results` | bool | `False` | Return structured JSON |

---

### BrightDataUnlocker

Access any public website, bypassing geo-restrictions and bot protection.

```python
from langchain_brightdata import BrightDataUnlocker

unlocker = BrightDataUnlocker()

# Simple access
content = unlocker.invoke("https://example.com")

# With options
content = unlocker.invoke({
    "url": "https://example.com/restricted",
    "country": "gb",
    "data_format": "markdown"
})
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | str | required | URL to access |
| `zone` | str | `"unlocker"` | Bright Data zone name |
| `country` | str | `None` | Two-letter country code |
| `data_format` | str | `None` | `None` (HTML), `"markdown"`, `"screenshot"` |

---

### BrightDataWebScraperAPI

Extract structured data from popular websites.

```python
from langchain_brightdata import BrightDataWebScraperAPI

scraper = BrightDataWebScraperAPI()

# Amazon product
product = scraper.invoke({
    "url": "https://www.amazon.com/dp/B08L5TNJHG",
    "dataset_type": "amazon_product"
})

# LinkedIn profile
profile = scraper.invoke({
    "url": "https://www.linkedin.com/in/satyanadella/",
    "dataset_type": "linkedin_person_profile"
})
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | str | required | URL to scrape |
| `dataset_type` | str | required | Type of data to extract |
| `zipcode` | str | `None` | Zipcode for location-specific data |

#### Supported Dataset Types (44 Datasets)

<details>
<summary><strong>E-Commerce (10 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `amazon_product` | Product details, pricing, specs | `url` (with /dp/) |
| `amazon_product_reviews` | Customer reviews and ratings | `url` (with /dp/) |
| `amazon_product_search` | Search results from Amazon | `keyword`, `url` |
| `walmart_product` | Walmart product data | `url` (with /ip/) |
| `walmart_seller` | Walmart seller information | `url` |
| `ebay_product` | eBay product data | `url` |
| `homedepot_products` | Home Depot product data | `url` |
| `zara_products` | Zara product data | `url` |
| `etsy_products` | Etsy product data | `url` |
| `bestbuy_products` | Best Buy product data | `url` |

</details>

<details>
<summary><strong>LinkedIn (5 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `linkedin_person_profile` | Professional profile data | `url` |
| `linkedin_company_profile` | Company information | `url` |
| `linkedin_job_listings` | Job listing details | `url` |
| `linkedin_posts` | Post content and engagement | `url` |
| `linkedin_people_search` | Search for people | `url`, `first_name`, `last_name` |

</details>

<details>
<summary><strong>Business Intelligence (2 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `crunchbase_company` | Company funding, investors, metrics | `url` |
| `zoominfo_company_profile` | B2B company intelligence | `url` |

</details>

<details>
<summary><strong>Instagram (4 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `instagram_profiles` | Profile data and stats | `url` |
| `instagram_posts` | Post content and engagement | `url` |
| `instagram_reels` | Reel content and metrics | `url` |
| `instagram_comments` | Comments on posts | `url` |

</details>

<details>
<summary><strong>Facebook (4 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `facebook_posts` | Post content and engagement | `url` |
| `facebook_marketplace_listings` | Marketplace listing data | `url` |
| `facebook_company_reviews` | Company reviews | `url`, `num_of_reviews` |
| `facebook_events` | Event details | `url` |

</details>

<details>
<summary><strong>TikTok (4 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `tiktok_profiles` | Profile data and stats | `url` |
| `tiktok_posts` | Video content and metrics | `url` |
| `tiktok_shop` | Shop product data | `url` |
| `tiktok_comments` | Comments on videos | `url` |

</details>

<details>
<summary><strong>YouTube (3 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `youtube_profiles` | Channel profile data | `url` |
| `youtube_videos` | Video content and metrics | `url` |
| `youtube_comments` | Comments on videos | `url`, `num_of_comments` (default: 10) |

</details>

<details>
<summary><strong>Google (3 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `google_maps_reviews` | Business reviews from Maps | `url`, `days_limit` (default: 3) |
| `google_shopping` | Shopping product data | `url` |
| `google_play_store` | App store data | `url` |

</details>

<details>
<summary><strong>Other Platforms (9 datasets)</strong></summary>

| Type | Description | Required Inputs |
|------|-------------|-----------------|
| `apple_app_store` | iOS app data | `url` |
| `x_posts` | X (Twitter) post data | `url` |
| `reddit_posts` | Reddit post data | `url` |
| `github_repository_file` | GitHub file content | `url` |
| `yahoo_finance_business` | Financial business data | `url` |
| `reuter_news` | News article data | `url` |
| `zillow_properties_listing` | Real estate listing data | `url` |
| `booking_hotel_listings` | Hotel listing data | `url` |

</details>

---

## Configuration

### Zone Configuration

Bright Data uses "zones" to manage different API configurations. You can set the zone at initialization or per-request.

#### Setting zone at initialization

```python
from langchain_brightdata import BrightDataSERP, BrightDataUnlocker

# SERP with custom zone
serp = BrightDataSERP(
    bright_data_api_key="your-api-key",
    zone="my_serp_zone"
)

# Unlocker with custom zone
unlocker = BrightDataUnlocker(
    bright_data_api_key="your-api-key",
    zone="my_unlocker_zone"
)
```

#### Setting zone per-request

```python
# Override zone for a specific request
results = serp.invoke({
    "query": "AI news",
    "zone": "different_zone"
})
```

#### Default zones

| Tool | Default Zone |
|------|--------------|
| `BrightDataSERP` | `serp` |
| `BrightDataUnlocker` | `unlocker` |

> **Note:** Zone names must match the zones configured in your [Bright Data dashboard](https://brightdata.com/cp/zones).

---

## Resources

- [Bright Data Documentation](https://docs.brightdata.com/integrations/langchain)
- [LangChain Tools Guide](https://docs.langchain.com/oss/python/integrations/providers/brightdata)
- [API Reference](https://docs.brightdata.com/api-reference)

---

## License

MIT License - see [LICENSE](LICENSE) for details.
