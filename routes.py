import time
from flask import (
    Blueprint, current_app, jsonify, render_template, request
)
from extensions import cache, limiter
from woot_service import fetch_all_deals, load_deals_from_file, save_deals_to_file

main_bp = Blueprint("main", __name__)
api_bp = Blueprint("api", __name__)


def _app_cfg() -> dict:
    cfg = current_app.config
    return {
        "WOOT_API_KEY": cfg["WOOT_API_KEY"],
        "WOOT_BASE_URL": cfg["WOOT_BASE_URL"],
        "FEED_NAMES": cfg["FEED_NAMES"],
        "MIN_SALE_PRICE": cfg["MIN_SALE_PRICE"],
        "MIN_DOLLAR_SAVINGS": cfg["MIN_DOLLAR_SAVINGS"],
        "MIN_PERCENT_OFF": cfg["MIN_PERCENT_OFF"],
        "HISTORICAL_LOWS_FILE": cfg["HISTORICAL_LOWS_FILE"],
    }


def _get_deals(force: bool = False) -> tuple:
    """
    1. If force=True, fetch fresh from Woot, save to memory + file
    2. Otherwise check memory cache first
    3. Fall back to file cache (survives restarts)
    4. Last resort: fetch live from Woot
    """
    if not force:
        # Check memory cache first
        cached = cache.get("all_deals")
        if cached:
            return cached["deals"], cached["fetched_at"]

        deals, fetched_at = load_deals_from_file()
        if deals:
            # Reload into memory cache
            cache.set("all_deals", {"deals": deals, "fetched_at": fetched_at})
            return deals, fetched_at

    # Data fetch
    print("Fetching deals...")
    deals = fetch_all_deals(_app_cfg())
    fetched_at = time.time()
    cache.set("all_deals", {"deals": deals, "fetched_at": fetched_at})
    return deals, fetched_at


# ── HTML Pages ────────────────────────────────────────────────────────────────

@main_bp.route("/")
def index():
    return render_template("index.html",
                           feed_names=current_app.config["FEED_NAMES"])


# ── JSON API ──────────────────────────────────────────────────────────────────

@api_bp.route("/deals")
@limiter.limit("20 per minute")
def get_deals():
    if not current_app.config.get("WOOT_API_KEY"):
        return jsonify({"error": "WOOT_API_KEY is not configured."}), 503

    try:
        deals, fetched_at = _get_deals()
    except Exception as e:
        current_app.logger.error(f"Deal fetch error: {e}")
        return jsonify({"error": "Failed to fetch deals."}), 502

    # Filter
    category = request.args.get("category", "").strip()
    query = request.args.get("q", "").strip().lower()
    if category and category != "All":
        deals = [d for d in deals if d["feed_name"] == category]
    if query:
        deals = [d for d in deals if query in d["title"].lower()]

    # Paginate
    per_page = current_app.config.get("DEALS_PER_PAGE", 12)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    total = len(deals)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_deals = deals[start: start + per_page]

    return jsonify({
        "deals": page_deals,
        "page": page,
        "total_pages": total_pages,
        "total_deals": total,
        "fetched_at": fetched_at,
        "per_page": per_page,
    })


@api_bp.route("/refresh", methods=["POST"])
@limiter.limit("5 per minute")
def refresh():
    if not current_app.config.get("WOOT_API_KEY"):
        return jsonify({"error": "WOOT_API_KEY is not configured."}), 503

    token = request.headers.get("X-Refresh-Token", "")
    expected = current_app.config.get("REFRESH_TOKEN", "")
    if expected and token != expected:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        start = time.time()
        deals, fetched_at = _get_deals(force=True)
        elapsed = round(time.time() - start, 2)
        return jsonify({
            "ok": True,
            "total_deals": len(deals),
            "elapsed_seconds": elapsed,
            "fetched_at": fetched_at,
        })
    except Exception as e:
        current_app.logger.error(f"Refresh error: {e}")
        return jsonify({"error": str(e)}), 502


@api_bp.route("/stats")
@limiter.limit("30 per minute")
def stats():
    if not current_app.config.get("WOOT_API_KEY"):
        return jsonify({"error": "WOOT_API_KEY is not configured."}), 503

    try:
        deals, fetched_at = _get_deals()
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    by_category: dict[str, int] = {}
    new_lows = price_drops = great_deals = 0

    for d in deals:
        by_category[d["feed_name"]] = by_category.get(d["feed_name"], 0) + 1
        if d["status"] == "NEW LOW":
            new_lows += 1
        elif d["status"] == "PRICE DROP":
            price_drops += 1
        else:
            great_deals += 1

    return jsonify({
        "total": len(deals),
        "new_lows": new_lows,
        "price_drops": price_drops,
        "great_deals": great_deals,
        "by_category": by_category,
        "fetched_at": fetched_at,
    })