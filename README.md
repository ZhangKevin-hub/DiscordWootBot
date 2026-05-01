# WootDeals Web Dashboard

A Flask web dashboard for monitoring Woot.com deals — refactored from a Discord bot into a clean multi-component web app, ready for PythonAnywhere.

---

## Project Structure

```
wootbot/
├── app.py              # Flask app factory (entry point)
├── config.py           # All configuration via environment variables
├── extensions.py       # Flask extension singletons (cache, rate limiter)
├── routes.py           # URL routes — HTML pages + JSON API
├── woot_service.py     # Woot API fetching, deal processing, historical lows
├── auth.py             # Optional dashboard password protection
├── wsgi.py             # PythonAnywhere WSGI entry point
├── requirements.txt
├── historical_lows.json  (auto-created at runtime)
├── templates/
│   ├── index.html      # Main dashboard
│   └── login.html      # Login page (if password is set)
└── static/
    ├── css/dashboard.css
    └── js/dashboard.js
```

---

## Deploying to PythonAnywhere

### 1. Upload your files
Upload the entire `wootbot/` folder to `/home/<yourusername>/wootbot/`.

### 2. Install dependencies
In a PythonAnywhere Bash console:
```bash
cd ~/wootbot
pip install -r requirements.txt --user
```

### 3. Configure a Web App
- Go to the **Web** tab → **Add a new web app**
- Choose **Manual configuration** → **Python 3.10+**
- Set **Source code**: `/home/<yourusername>/wootbot`
- Set **Working directory**: `/home/<yourusername>/wootbot`
- Edit the **WSGI configuration file** and replace its contents with:
  ```python
  import sys, os
  sys.path.insert(0, '/home/<yourusername>/wootbot')
  from app import create_app
  application = create_app()
  ```

### 4. Set Environment Variables
In the **Web** tab → **Environment variables** section:

| Variable            | Required | Description |
|---------------------|----------|-------------|
| `WOOT_API_KEY`      | ✅ Yes   | Your Woot developer API key |
| `SECRET_KEY`        | ✅ Yes   | Random secret for Flask sessions. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DASHBOARD_PASSWORD`| Optional | Set to enable login protection. Leave blank for open access. |

### 5. Reload and visit your app
Hit **Reload** in the Web tab, then open `https://<yourusername>.pythonanywhere.com`.

---

## API Endpoints

All endpoints require authentication (if `DASHBOARD_PASSWORD` is set).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard UI |
| GET | `/login` | Login page |
| GET | `/logout` | Clear session |
| GET | `/api/deals` | Paginated deals (params: `page`, `category`, `q`) |
| POST | `/api/refresh` | Force a fresh Woot API fetch |
| GET | `/api/stats` | Summary counts by status and category |

---

## Deal Filter Thresholds (config.py)

| Setting | Default | Meaning |
|---------|---------|---------|
| `MIN_SALE_PRICE` | $75.00 | Minimum sale price to qualify |
| `MIN_DOLLAR_SAVINGS` | $40.00 | Minimum dollar amount saved |
| `MIN_PERCENT_OFF` | 50% | Minimum discount percentage |

Change these in `config.py` or override via environment variables if desired.

---

## Security Notes

- **No secrets in code** — all keys/passwords are loaded from environment variables only.
- **Rate limiting** — Flask-Limiter protects all API endpoints from abuse.
- **Input sanitization** — all user-supplied values (search, category) are validated/escaped.
- **Session auth** — optional `DASHBOARD_PASSWORD` protects the entire dashboard.
- **HTTPS** — PythonAnywhere provides HTTPS automatically on `.pythonanywhere.com` domains.
