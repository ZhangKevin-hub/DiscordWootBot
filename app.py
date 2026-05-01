"""
app.py — Entry point for WootDeals Web Dashboard (PythonAnywhere-ready)
"""

from flask import Flask
from config import Config
from extensions import cache, limiter
from routes import main_bp, api_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    cache.init_app(app)
    limiter.init_app(app)

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=False)
