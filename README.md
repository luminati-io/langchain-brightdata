# 🌟 langchain-brightdata

[![PyPI - Version](https://img.shields.io/pypi/v/langchain-brightdata?style=flat-square&label=PyPI)](https://pypi.org/project/langchain-brightdata/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![LangChain](https://img.shields.io/badge/LangChain-Integration-blue)](https://python.langchain.com)

**Access powerful web data capabilities for your AI agents with [Bright Data](https://brightdata.com)!** 🚀

## 📋 Overview

This package provides LangChain integrations for Bright Data's suite of web data collection tools, allowing your AI agents to:

- 🔍 Collect search engine results with geo-targeting
- 🌐 Access websites that might be geo-restricted or protected by anti-bot systems
- 📊 Extract structured data from popular websites like Amazon, LinkedIn, and more

Perfect for AI agents that need real-time web data!

## 🛠️ Installation

```bash
pip install langchain-brightdata
```

## 🔑 Setup

You'll need a Bright Data API key to use these tools. Set it as an environment variable:

```python
import os
os.environ["BRIGHT_DATA_API_KEY"] = "your-api-key"
```

Or pass it directly when initializing tools:

```python
from langchain_brightdata import BrightDataSERP
tool = BrightDataSERP(bright_data_api_key="your-api-key")
```

## 🧰 Available Tools

### 🔍 BrightDataSERP

Perform search engine queries with customizable geo-targeting, device type, and language settings.

```python
from langchain_brightdata import BrightDataSERP

# Basic usage
serp_tool = BrightDataSERP(bright_data_api_key="your-api-key")
results = serp_tool.invoke("latest AI research papers")

# Advanced usage with parameters
results = serp_tool.invoke({
    "query": "best electric vehicles",
    "country": "de",  # Get results as if searching from Germany
    "language": "de",  # Get results in German
    "search_type": "shop",  # Get shopping results
    "device_type": "mobile",  # Simulate a mobile device
    "results_count": 15
})
```

#### 🎛️ Customization Options

| Parameter | Type | Description |
|:----------|:-----|:------------|
| `query` | str | The search query to perform |
| `search_engine` | str | Search engine to use (default: "google") |
| `country` | str | Two-letter country code for localized results (default: "us") |
| `language` | str | Two-letter language code (default: "en") |
| `results_count` | int | Number of results to return (default: 10) |
| `search_type` | str | Type of search: None (web), "isch" (images), "shop", "nws" (news), "jobs" |
| `device_type` | str | Device type: None (desktop), "mobile", "ios", "android" |
| `parse_results` | bool | Whether to return structured JSON (default: False) |

### 🌐 BrightDataUnlocker

Access ANY public website that might be geo-restricted or protected by anti-bot systems.

```python
from langchain_brightdata import BrightDataUnlocker

# Basic usage
unlocker_tool = BrightDataUnlocker(bright_data_api_key="your-api-key")
result = unlocker_tool.invoke("https://example.com")

# Advanced usage with parameters
result = unlocker_tool.invoke({
    "url": "https://example.com/region-restricted-content",
    "country": "gb",  # Access as if from Great Britain
    "data_format": "markdown",  # Get content in markdown format
    "zone": "unlocker"  # Use the unlocker zone
})
```

#### 🎛️ Customization Options

| Parameter | Type | Description |
|:----------|:-----|:------------|
| `url` | str | The URL to access |
| `format` | str | Format of the response content (default: "raw") |
| `country` | str | Two-letter country code for geo-specific access (e.g., "us", "gb") |
| `zone` | str | Bright Data zone to use (default: "unblocker") |
| `data_format` | str | Output format: None (HTML), "markdown", or "screenshot" |

### 📊 BrightDataWebScraperAPI

Extract structured data from 100+ popular domains, including Amazon, LinkedIn, and more.

```python
from langchain_brightdata import BrightDataWebScraperAPI

# Initialize the tool
scraper_tool = BrightDataWebScraperAPI(bright_data_api_key="your-api-key")

# Extract Amazon product data
results = scraper_tool.invoke({
    "url": "https://www.amazon.com/dp/B08L5TNJHG",
    "dataset_type": "amazon_product"
})

# Extract LinkedIn profile data
linkedin_results = scraper_tool.invoke({
    "url": "https://www.linkedin.com/in/satyanadella/",
    "dataset_type": "linkedin_person_profile"
})
```

#### 🎛️ Customization Options

| Parameter | Type | Description |
|:----------|:-----|:------------|
| `url` | str | The URL to extract data from |
| `dataset_type` | str | Type of dataset to use (e.g., "amazon_product") |
| `zipcode` | str | Optional zipcode for location-specific data |

#### 📂 Available Dataset Types

| Dataset Type | Description |
|:-------------|:------------|
| `amazon_product` | Extract detailed Amazon product data |
| `amazon_product_reviews` | Extract Amazon product reviews |
| `linkedin_person_profile` | Extract LinkedIn person profile data |
| `linkedin_company_profile` | Extract LinkedIn company profile data |


## 📚 Additional Resources

- [Bright Data Official Documentation](https://docs.brightdata.com/introduction)
- [LangChain Documentation](https://python.langchain.com/docs/integrations/tools/brightdata)