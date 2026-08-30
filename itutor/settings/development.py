"""
Local development settings. This is what runs on your machine via
`python manage.py runserver`.
"""
from datetime import timedelta

from decouple import config

from .base import *  # noqa: F401, F403

SECRET_KEY = config("SECRET_KEY", default="django-insecure-dev-only-change-in-prod")

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Long-lived tokens purely for dev convenience, so you're not re-logging
# in constantly while testing in Postman. NEVER carry these values into
# production.py.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# Allows your frontend (running on e.g. localhost:5173 for Vite, or
# localhost:3000 for React) to call this API from the browser during
# development. Wildcard-free — only these trusted origins. 5174/5175 are
# included because Vite automatically falls back to the next free port
# when 5173 is already in use (a very common local scenario).
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]
