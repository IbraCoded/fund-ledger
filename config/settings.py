"""Django settings. Everything environment-specific comes from env vars (12-factor)."""

from __future__ import annotations

import os
from pathlib import Path

from observability.logging import configure_logging

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "funds",
    "ledger",
    "operations",
    "observability",
    "access",
]

MIDDLEWARE = [
    "observability.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "ledger"),
        "USER": env("POSTGRES_USER", "ledger"),
        "PASSWORD": env("POSTGRES_PASSWORD", "ledger"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("CONN_MAX_AGE", "0")),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["access.authentication.ApiKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "api.throttling.MutationThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", "30/min"),
        "user": env("THROTTLE_USER", "600/min"),
        "mutations": env("THROTTLE_MUTATIONS", "60/min"),
    },
    # Behind Caddy, the real client IP is the last X-Forwarded-For hop. 0 locally, 1 in production.
    "NUM_PROXIES": int(env("NUM_PROXIES", "0")),
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["api.parsers.DecimalJSONParser"],
    "EXCEPTION_HANDLER": "api.exceptions.exception_handler",
}

configure_logging(json_output=env("LOG_FORMAT", "json") == "json", level=env("LOG_LEVEL", "INFO"))
