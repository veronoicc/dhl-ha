"""Constants for the DHL integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dhl"

# Configuration and options keys
CONF_POST_NUMBER: Final = "post_number"
CONF_EMAIL: Final = "email"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_DHLA0: Final = "dhla0"
CONF_DHLR0: Final = "dhlr0"
CONF_DHLB: Final = "dhlb"
CONF_VERFOLGEN_CSRF: Final = "verfolgen_csrf"
CONF_AUTH_METHOD: Final = "auth_method"
AUTH_METHOD_CREDENTIALS: Final = "credentials"
AUTH_METHOD_COOKIES: Final = "cookies"

CONF_INCLUDE_ARCHIVED: Final = "include_archived"
CONF_POLL_INTERVAL: Final = "poll_interval"

DEFAULT_POLL_INTERVAL: Final = 15  # minutes
MIN_POLL_INTERVAL: Final = 5
MAX_POLL_INTERVAL: Final = 120
DEFAULT_INCLUDE_ARCHIVED: Final = False

# Services
SERVICE_GET_PARCELS: Final = "get_parcels"
SERVICE_REFRESH_PARCELS: Final = "refresh_parcels"

# Attributes
ATTR_TRACKING_NUMBER: Final = "tracking_number"
ATTR_PARCEL_NAME: Final = "parcel_name"
ATTR_DIRECTION: Final = "direction"
ATTR_STATUS: Final = "status"
ATTR_RECIPIENT: Final = "recipient"
ATTR_DELIVERY: Final = "delivery"
ATTR_PROGRESS: Final = "progress"
ATTR_EXPECTED_DELIVERY: Final = "expected_delivery"
ATTR_SENDER_LOGO: Final = "sender_logo"
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_INCLUDE_ARCHIVED: Final = "include_archived"

# API & OAuth parameters
AUTH0_CLIENT_ID: Final = "kVcamHTNbhMbYBL41DgCCF4RYrTSkWyo"
AUTH0_DOMAIN: Final = "account.dhl.de"
DHL_PORTAL_HOST: Final = "www.dhl.de"
API_SEARCH_URL: Final = "https://www.dhl.de/int-verfolgen/data/search"
API_REFRESH_URL: Final = "https://www.dhl.de/int-login/refresh"
