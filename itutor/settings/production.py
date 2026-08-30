"""
Production settings. Every value that matters for security is pulled
from environment variables — nothing sensitive is hardcoded here, so
this file is safe to commit to version control.
"""
from datetime import timedelta

from decouple import Csv, config

from .base import *  # noqa: F401, F403

# No default here — if SECRET_KEY isn't set in the environment, the
# app should fail to start rather than silently run with a weak key.
SECRET_KEY = config("SECRET_KEY")

DEBUG = False

# Comma-separated list in the environment, e.g.
# ALLOWED_HOSTS=api.yourapp.com,yourapp.com
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# Short-lived tokens — this is the real security posture. The frontend
# is responsible for silently calling /api/auth/refresh/ before the
# access token expires.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv(), default="")

# HTTPS / transport security — assumes the app sits behind a reverse
# proxy (Nginx, or the hosting platform's own proxy) that terminates
# SSL and forwards this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000  # 1 year, standard once you're confident HTTPS is solid
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"