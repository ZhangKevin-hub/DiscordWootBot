import json
import os
import random
import time
from typing import Any
from concurrent.futures import ThreadPoolExecutor
import requests

CACHE_FILE = "deals_cache.json"


def save_deals_to_file(deals: list) -> None:
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"deals": deals, "fetched_at": time.time()}, f)
        print(f"Saved {len(deals)} deals to file cache.")
    except Exception as e:
        print(f"ERROR saving deals to file: {e}")

def load_deals_from_file() -> tuple:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                return data.get("deals", []), data.get("fetched_at")
    except Exception as e:
        print(f"ERROR loading deals from file: {e}")
    return [], None


LOWS_FILE = "historical_lows.json"

def load_historical_lows(app_config) -> dict:
    try:
        if os.path.exists(LOWS_FILE):
            with open(LOWS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"WARNING: Could not load historical lows: {e}")
    return {}

def save_historical_low(app_config, offer_id: str, price: float, cache: dict) -> None:
    cache[offer_id] = price
    try:
        with open(LOWS_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"ERROR saving historical lows: {e}")


def fetch_feed(feed_name: str, api_key: str, base_url: str) -> list[dict]:
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


def process_raw_deal(raw: dict, feed_name: str) -> dict[str, Any]:
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
    results = {}

    batch_size = 3
    batches = [feed_names[i:i+batch_size] for i in range(0, len(feed_names), batch_size)]

    for batch in batches:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(fetch_feed, feed_name, api_key, base_url): feed_name
                for feed_name in batch
            }
            for future in futures:
                feed_name = futures[future]
                try:
                    results[feed_name] = future.result()
                except Exception as e:
                    print(f"Error fetching {feed_name}: {e}")
                    results[feed_name] = []
        time.sleep(0.5)

    for feed_name in feed_names:
        for raw in results.get(feed_name, []):
            deal = process_raw_deal(raw, feed_name)
            if not passes_filters(deal, filter_cfg):
                continue

            offer_id = deal["offer_id"]
            current_low = historical_lows.get(offer_id, float("inf"))

            if deal["sale_price"] < current_low:
                save_historical_low(app_config, offer_id, deal["sale_price"], historical_lows)
                deal["status"] = "NEW LOW" if current_low == float("inf") else "PRICE DROP"
                deal["prev_low"] = None if current_low == float("inf") else current_low
            else:
                deal["status"] = "GREAT DEAL"
                deal["prev_low"] = None

            qualified.append(deal)

    qualified.sort(key=lambda d: d["discount_percent"], reverse=True)
    save_deals_to_file(qualified)
    return qualified