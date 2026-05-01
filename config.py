"""
config.py — All configuration loaded from environment variables.
Never hardcode secrets. On PythonAnywhere, set these in the
Web tab > Environment Variables section.
"""

import os
import secrets


class Config:
    # ── Security ──────────────────────────────────────────────────────────────
    # Flask secret key for sessions/CSRF. Auto-generated if not set, but
    # you SHOULD set a persistent value in your environment.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    # ── API Keys ──────────────────────────────────────────────────────────────
    WOOT_API_KEY = os.environ.get("WOOT_API_KEY", "")

    # Optional: simple password to protect the dashboard.
    # Set DASHBOARD_PASSWORD in environment. Leave blank to disable auth.
    DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

    # ── Cache (Flask-Caching, SimpleCache for single-process) ─────────────────
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes — matches original bot logic

    # ── Rate limiting (Flask-Limiter) ─────────────────────────────────────────
    RATELIMIT_DEFAULT = "30 per minute"
    RATELIMIT_STORAGE_URI = "memory://"

    # ── Woot API ───────────────────────────────────────────────────────────────
    WOOT_BASE_URL = "https://developer.woot.com"
    FEED_NAMES = [
        "All", "Clearance", "Computers", "Electronics", "Featured",
        "Home", "Gourmet", "Shirts", "Sports", "Tools", "Wootoff"
    ]

    # ── Deal filter thresholds ─────────────────────────────────────────────────
    MIN_SALE_PRICE = 75.00
    MIN_PERCENT_OFF = 50.0
    MIN_DOLLAR_SAVINGS = 40.00

    # ── Pagination ─────────────────────────────────────────────────────────────
    DEALS_PER_PAGE = 12

    # ── Persistence ───────────────────────────────────────────────────────────
    HISTORICAL_LOWS_FILE = "historical_lows.json"
