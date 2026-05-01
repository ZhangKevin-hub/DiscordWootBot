"""
wsgi.py — PythonAnywhere WSGI entry point.

In the PythonAnywhere Web tab, set:
  Source code:       /home/<yourusername>/wootbot
  Working directory: /home/<yourusername>/wootbot
  WSGI config file:  point it to this file
  Python version:    3.10+

Environment variables to set in the Web tab:
  WOOT_API_KEY       — your Woot developer API key
  SECRET_KEY         — a long random string (e.g. from `python -c "import secrets; print(secrets.token_hex(32))"`)
  DASHBOARD_PASSWORD — (optional) password to protect the dashboard
"""

import sys
import os

# Ensure the app directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app

application = create_app()
