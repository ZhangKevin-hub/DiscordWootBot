"""
extensions.py — Flask extension instances (initialized without app).
Import from here to avoid circular imports.
"""

from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

cache = Cache()
limiter = Limiter(key_func=get_remote_address)
