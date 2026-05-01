"""
routes.py — Flask route blueprints.

main_bp  → HTML pages  (/, /login, /logout)
api_bp   → JSON API    (/api/deals, /api/refresh, /api/stats)
"""

import time
from flask import (
    Blueprint, current_app, jsonify, render_template,
    request, session, redirect, url_for
)
from extensions import cache, limiter
from woot_service import fetch_all_deals

main_bp = Blueprint("main", __name__)
api_bp = Blueprint("api", __name__)


# ── Helper ────────────────────────────────────────────────────────────────────

def _app_cfg() -> dict:
    """Expose selected Flask config keys as a plain dict for the service layer."""
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


def _get_cached_deals(force: bool = False) -> tuple[list, float]:
    """Return (deals, fetched_at_timestamp). Uses Flask-Cache."""
    cached = None if force else cache.get("all_deals")
    if cached is not None:
        return cached["deals"], cached["fetched_at"]

    deals = fetch_all_deals(_app_cfg())
    payload = {"deals": deals, "fetched_at": time.time()}
    cache.set("all_deals", payload)
    return deals, payload["fetched_at"]


# ── HTML Pages ────────────────────────────────────────────────────────────────

@main_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    error = None
    if request.method == "POST":
        password = current_app.config.get("DASHBOARD_PASSWORD", "")
        if request.form.get("password") == password:
            session["authenticated"] = True
            session.permanent = False
            next_url = request.args.get("next") or url_for("main.index")
            return redirect(next_url)
        error = "Incorrect password."
    return render_template("login.html", error=error)


@main_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@main_bp.route("/")
def index():
    return render_template("index.html",
                           feed_names=current_app.config["FEED_NAMES"])


# ── JSON API ──────────────────────────────────────────────────────────────────

@api_bp.route("/deals")
@limiter.limit("20 per minute")
def get_deals():
    """
    GET /api/deals
    Query params:
      category  — filter by feed name (optional)
      q         — search keyword (optional)
      page      — 1-based page number (default 1)
    """
    if not current_app.config.get("WOOT_API_KEY"):
        return jsonify({"error": "WOOT_API_KEY is not configured on the server."}), 503

    try:
        deals, fetched_at = _get_cached_deals()
    except Exception as e:
        current_app.logger.error(f"Deal fetch error: {e}")
        return jsonify({"error": "Failed to fetch deals from Woot API."}), 502

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
    """POST /api/refresh — Force a fresh fetch, bypassing cache."""
    if not current_app.config.get("WOOT_API_KEY"):
        return jsonify({"error": "WOOT_API_KEY is not configured on the server."}), 503

    try:
        start = time.time()
        deals, fetched_at = _get_cached_deals(force=True)
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
    """GET /api/stats — Summary counts and metadata."""
    if not current_app.config.get("WOOT_API_KEY"):
        return jsonify({"error": "WOOT_API_KEY is not configured."}), 503

    try:
        deals, fetched_at = _get_cached_deals()
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
