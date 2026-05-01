"""
woot_service.py — Woot API interaction, deal processing, and historical lows.
All functions are synchronous (suitable for PythonAnywhere's WSGI environment).
"""

import json
import os
import random
import time
from typing import Any

import requests


# ── Historical Lows Persistence ───────────────────────────────────────────────

def _lows_path(app_config) -> str:
    return app_config.get("HISTORICAL_LOWS_FILE", "historical_lows.json")


def load_historical_lows(app_config) -> dict:
    path = _lows_path(app_config)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"WARNING: Could not load historical lows: {e}")
    return {}


def save_historical_low(app_config, offer_id: str, price: float, cache: dict) -> None:
    """Update the in-memory cache dict and persist to disk."""
    cache[offer_id] = price
    path = _lows_path(app_config)
    try:
        with open(path, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"ERROR saving historical lows: {e}")


# ── Raw API Fetching ──────────────────────────────────────────────────────────

def fetch_feed(feed_name: str, api_key: str, base_url: str) -> list[dict]:
    """
    Fetches one Woot feed with retry/back-off.
    Returns a list of raw item dicts (may be empty on error).
    """
    url = f"{base_url}/feed/{feed_name}"
    headers = {"Accept": "application/json", "x-api-key": api_key}

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("Items", [])
            elif resp.status_code == 429:
                time.sleep(2 ** attempt + random.uniform(0.5, 1.0))
            else:
                resp.raise_for_status()
        except requests.exceptions.Timeout:
            print(f"Timeout fetching {feed_name} (attempt {attempt + 1})")
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {feed_name}: {e}")
            break
    return []


# ── Deal Processing ───────────────────────────────────────────────────────────

def process_raw_deal(raw: dict, feed_name: str) -> dict[str, Any]:
    """Extract clean metrics from a raw Woot API item."""
    deal: dict[str, Any] = {
        "offer_id": raw.get("OfferId", "N/A"),
        "title": raw.get("Title", "No Title"),
        "url": raw.get("Url", "#"),
        "feed_name": feed_name,
        "sale_price": None,
        "list_price": None,
        "discount_percent": 0.0,
        "savings_amount": 0.0,
        "is_sold_out": raw.get("IsSoldOut", True),
        "image_url": None,
    }

    # Extract image
    photos = raw.get("Photos", [])
    if photos and isinstance(photos, list):
        deal["image_url"] = photos[0].get("Url") or photos[0].get("url")

    sale_data = raw.get("SalePrice")
    list_data = raw.get("ListPrice")

    if sale_data and list_data:
        try:
            sale_min = sale_data.get("Minimum")
            list_min = list_data.get("Minimum")
            if (
                isinstance(sale_min, (int, float))
                and isinstance(list_min, (int, float))
                and list_min > 0
                and list_min > sale_min
            ):
                deal["sale_price"] = sale_min
                deal["list_price"] = list_min
                deal["discount_percent"] = round(
                    ((list_min - sale_min) / list_min) * 100, 2
                )
                deal["savings_amount"] = round(list_min - sale_min, 2)
        except (TypeError, AttributeError):
            pass

    return deal


def passes_filters(deal: dict, config) -> bool:
    """Returns True if the deal meets all configured thresholds."""
    if deal["sale_price"] is None or deal["is_sold_out"]:
        return False
    if deal["sale_price"] < config["MIN_SALE_PRICE"]:
        return False
    if deal["savings_amount"] < config["MIN_DOLLAR_SAVINGS"]:
        return False
    if deal["discount_percent"] < config["MIN_PERCENT_OFF"]:
        return False
    return True


# ── Full Refresh ──────────────────────────────────────────────────────────────

def fetch_all_deals(app_config: dict) -> list[dict]:
    """
    Fetches every feed, filters deals, annotates with historical-low status.
    Returns a list sorted by discount_percent descending.
    """
    api_key = app_config.get("WOOT_API_KEY", "")
    base_url = app_config.get("WOOT_BASE_URL", "https://developer.woot.com")
    feed_names = app_config.get("FEED_NAMES", [])

    filter_cfg = {
        "MIN_SALE_PRICE": app_config.get("MIN_SALE_PRICE", 75.0),
        "MIN_DOLLAR_SAVINGS": app_config.get("MIN_DOLLAR_SAVINGS", 40.0),
        "MIN_PERCENT_OFF": app_config.get("MIN_PERCENT_OFF", 50.0),
    }

    historical_lows = load_historical_lows(app_config)
    qualified: list[dict] = []

    for feed_name in feed_names:
        raw_items = fetch_feed(feed_name, api_key, base_url)
        for raw in raw_items:
            deal = process_raw_deal(raw, feed_name)
            if not passes_filters(deal, filter_cfg):
                continue

            offer_id = deal["offer_id"]
            current_low = historical_lows.get(offer_id, float("inf"))

            if deal["sale_price"] < current_low:
                save_historical_low(app_config, offer_id, deal["sale_price"], historical_lows)
                deal["status"] = (
                    "NEW LOW" if current_low == float("inf") else f"PRICE DROP"
                )
                deal["prev_low"] = None if current_low == float("inf") else current_low
            else:
                deal["status"] = "GREAT DEAL"
                deal["prev_low"] = None

            qualified.append(deal)

        # Polite delay between feed calls
        time.sleep(random.uniform(1.1, 1.3))

    qualified.sort(key=lambda d: d["discount_percent"], reverse=True)
    return qualified
