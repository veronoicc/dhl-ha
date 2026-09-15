"""API client for DHL Web Internal API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .const import (
    API_REFRESH_URL,
    API_SEARCH_URL,
    AUTH0_DOMAIN,
    DHL_PORTAL_HOST,
    DOMAIN,
)
from .models import Parcel

_LOGGER = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class DHLError(HomeAssistantError):
    """Base error for DHL integration."""

    translation_domain = DOMAIN


class DHLAuthError(DHLError):
    """Authentication or authorization failure."""


class DHLConnectionError(DHLError):
    """Network or connection failure."""


class DHLRateLimitError(DHLError):
    """Rate limit exceeded."""


@dataclass
class DHLCredentials:
    """Container for authenticated session credentials."""

    email: str
    post_number: str
    display_name: str
    dhla0: str
    dhlr0: str
    dhlb: str
    verfolgen_csrf: str
    expires_at: float


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode JWT payload without verifying signature."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(data, dict):
            return {}

        # Normalize email from known Auth0 / CIAM claim variations
        if "email" not in data:
            for key in (
                "https://account.dhl.de/email",
                "preferred_username",
                "user_email",
                "mail",
            ):
                if val := data.get(key):
                    data["email"] = str(val)
                    break
            if "email" not in data and (sub := str(data.get("sub", ""))) and "@" in sub:
                data["email"] = sub.split("|")[-1]

        # Normalize post_number from known claim variations
        if "post_number" not in data:
            for key in (
                "https://account.dhl.de/post_number",
                "postnumber",
                "post_nummer",
                "postNumber",
            ):
                if val := data.get(key):
                    data["post_number"] = str(val)
                    break

        return data
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as err:
        _LOGGER.debug("Failed to decode JWT payload: %s", err)
        return {}


def _mask_identifier(val: str | None) -> str:
    """Mask email or username for sensitive logging."""
    if not val:
        return "<none>"
    if "@" in val:
        parts = val.split("@", 1)
        name, domain = parts[0], parts[1]
        masked_name = name[:2] + "***" if len(name) > 2 else "***"
        return f"{masked_name}@{domain}"
    if len(val) > 4:
        return f"{val[:2]}***{val[-2:]}"
    return "***"


def _mask_token(token: str | None) -> str:
    """Mask JWT or session token for debug logging."""
    if not token:
        return "<empty>"
    if len(token) > 12:
        return f"{token[:4]}...{token[-4:]} (len={len(token)})"
    return "***"


def _extract_error_detail(html: str) -> str:
    """Extract error code or message from DHL/Akamai error page."""
    import re

    match = re.search(r"<dt>Fehlercode:?</dt>\s*<dd>(.*?)</dd>", html, re.IGNORECASE)
    if match:
        return f"Akamai WAF Bot Protection Block (Error code: {match.group(1).strip()})"
    h1_match = re.search(r"<h1>(.*?)</h1>", html, re.IGNORECASE)
    if h1_match:
        return f"DHL Error: {h1_match.group(1).strip()}"
    return "Blocked by DHL security / Akamai WAF"


class DHLClient:
    """Client for DHL web internal tracking API and CIAM login."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        credentials: DHLCredentials | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.credentials = credentials

    @property
    def is_token_expired(self) -> bool:
        """Check if access token has expired."""
        if not self.credentials:
            return True
        return time.time() >= self.credentials.expires_at

    def expires_soon(self, within_seconds: int = 300) -> bool:
        """Check if access token will expire soon."""
        if not self.credentials:
            return True
        return time.time() >= (self.credentials.expires_at - within_seconds)

    async def async_login(self, username: str, password: str) -> DHLCredentials:
        """Execute CIAM Auth0 login flow and acquire session tokens."""
        _LOGGER.debug(
            "Initiating DHL CIAM authentication flow for user %s",
            _mask_identifier(username),
        )
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }

        try:
            # Step 1: Initialize login from Service Provider
            init_url = (
                f"https://{DHL_PORTAL_HOST}/int-login/login?"
                "authenticationLevel=3&authenticationMethod=pwd"
                "&requireUserInputString=login&loginHint=&headerID=null"
                "&footerID=null&registrationID=null&allowRegistration=false"
                "&uiLocales=de&bAfterMasterDataChange=false"
            )
            _LOGGER.debug("CIAM Step 1: Requesting login init from %s", init_url)
            async with self._session.get(
                init_url,
                headers=headers,
                allow_redirects=False,
            ) as resp:
                _LOGGER.debug(
                    "CIAM Step 1 response status: %s",
                    resp.status,
                )
                if resp.status not in (302, 303, 307):
                    text_sample = (await resp.text())[:1000]
                    detail = _extract_error_detail(text_sample)
                    _LOGGER.warning(
                        "CIAM Step 1 failed (HTTP %s, %s). Please use the 'Session cookies' authentication method instead.",
                        resp.status,
                        detail,
                    )
                    raise DHLAuthError(
                        f"Login initialization failed (HTTP {resp.status}: {detail}). Please use 'Session cookies' authentication method."
                    )
                auth_url = resp.headers.get("Location")
                if not auth_url:
                    raise DHLAuthError("Missing Location header in login init")
                _LOGGER.debug("CIAM Step 1 redirect target: %s", auth_url.split("?")[0])

            # Step 2: GET Auth0 Authorize entrypoint
            _LOGGER.debug("CIAM Step 2: Requesting Auth0 authorize entrypoint")
            async with self._session.get(
                auth_url,
                headers=headers,
                allow_redirects=False,
            ) as resp:
                _LOGGER.debug("CIAM Step 2 response status: %s", resp.status)
                if resp.status not in (302, 303, 307):
                    text_sample = (await resp.text())[:1000]
                    detail = _extract_error_detail(text_sample)
                    _LOGGER.warning(
                        "CIAM Step 2 failed (HTTP %s, %s). Please use the 'Session cookies' authentication method instead.",
                        resp.status,
                        detail,
                    )
                    raise DHLAuthError(
                        f"Authorize entrypoint failed (HTTP {resp.status}: {detail}). Please use 'Session cookies' authentication method."
                    )
                identifier_loc = resp.headers.get("Location")
                if not identifier_loc:
                    raise DHLAuthError("Missing identifier redirect URL")
                identifier_url = urljoin(f"https://{AUTH0_DOMAIN}", identifier_loc)
                _LOGGER.debug(
                    "CIAM Step 2 identifier URL: %s", identifier_url.split("?")[0]
                )

            parsed_id = urlparse(identifier_url)
            state = parse_qs(parsed_id.query).get("state", [""])[0]
            if not state:
                raise DHLAuthError("Missing state parameter from Auth0")

            # Step 3: POST username / email identifier
            _LOGGER.debug("CIAM Step 3: Submitting username/email identifier")
            id_data = {
                "state": state,
                "username": username,
                "js-available": "true",
                "webauthn-available": "true",
                "is-brave": "false",
                "webauthn-platform-available": "false",
                "action": "default",
            }
            async with self._session.post(
                identifier_url,
                data=id_data,
                headers={
                    **headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                allow_redirects=False,
            ) as resp:
                _LOGGER.debug("CIAM Step 3 response status: %s", resp.status)
                if resp.status not in (302, 303, 307):
                    text_sample = (await resp.text())[:1000]
                    detail = _extract_error_detail(text_sample)
                    _LOGGER.warning(
                        "CIAM Step 3 failed (HTTP %s, %s). Identifier rejected. Please use 'Session cookies' authentication method.",
                        resp.status,
                        detail,
                    )
                    raise DHLAuthError(
                        f"Invalid username or identifier rejected (HTTP {resp.status}: {detail}). Please use 'Session cookies' authentication method."
                    )
                password_loc = resp.headers.get("Location")
                if not password_loc:
                    raise DHLAuthError("Missing password redirect URL")
                password_url = urljoin(f"https://{AUTH0_DOMAIN}", password_loc)
                _LOGGER.debug(
                    "CIAM Step 3 password URL: %s", password_url.split("?")[0]
                )

            parsed_pwd = urlparse(password_url)
            state_pwd = parse_qs(parsed_pwd.query).get("state", [state])[0]

            # Step 4: POST password
            _LOGGER.debug("CIAM Step 4: Submitting password")
            pwd_data = {
                "state": state_pwd,
                "username": username,
                "password": password,
                "action": "default",
            }
            async with self._session.post(
                password_url,
                data=pwd_data,
                headers={
                    **headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                allow_redirects=False,
            ) as resp:
                _LOGGER.debug("CIAM Step 4 response status: %s", resp.status)
                if resp.status not in (302, 303, 307):
                    text_sample = (await resp.text())[:1000]
                    detail = _extract_error_detail(text_sample)
                    _LOGGER.warning(
                        "CIAM Step 4 failed (HTTP %s, %s). DHL Akamai Bot Manager blocked automated password submission. Please use the 'Session cookies' authentication method instead.",
                        resp.status,
                        detail,
                    )
                    raise DHLAuthError(
                        f"DHL Akamai Bot Manager blocked login ({detail}). Please use the 'Session cookies' authentication method instead."
                    )
                resume_loc = resp.headers.get("Location")
                if not resume_loc:
                    raise DHLAuthError("Missing resume redirect URL")
                if "login/password" in resume_loc or "u/login" in resume_loc:
                    _LOGGER.warning(
                        "CIAM Step 4 redirected back to login (invalid password or 2FA prompt required)"
                    )
                    raise DHLAuthError(
                        "Invalid password or 2FA required. Please use 'Session cookies' authentication method."
                    )
                resume_url = urljoin(f"https://{AUTH0_DOMAIN}", resume_loc)
                _LOGGER.debug("CIAM Step 4 resume URL: %s", resume_url.split("?")[0])

            # Step 5: Resume & obtain auth code
            _LOGGER.debug("CIAM Step 5: Resuming Auth0 authorization")
            async with self._session.get(
                resume_url,
                headers=headers,
                allow_redirects=False,
            ) as resp:
                _LOGGER.debug("CIAM Step 5 response status: %s", resp.status)
                if resp.status not in (302, 303, 307):
                    text_sample = (await resp.text())[:300]
                    _LOGGER.warning(
                        "CIAM Step 5 failed: Resume returned HTTP %s. Body: %s",
                        resp.status,
                        text_sample,
                    )
                    raise DHLAuthError("Failed to resume Auth0 session")
                token_loc = resp.headers.get("Location")
                if not token_loc:
                    raise DHLAuthError("Missing token callback redirect URL")
                token_url = urljoin(f"https://{DHL_PORTAL_HOST}", token_loc)
                _LOGGER.debug(
                    "CIAM Step 5 token callback URL: %s", token_url.split("?")[0]
                )

            # Step 6: Code exchange at SP callback
            _LOGGER.debug(
                "CIAM Step 6: Exchanging authorization code at SP callback %s",
                token_url.split("?")[0],
            )
            async with self._session.get(
                token_url,
                headers=headers,
                allow_redirects=False,
            ) as resp:
                _LOGGER.debug("CIAM Step 6 response status: %s", resp.status)
                if resp.status != 200 and resp.status not in (302, 303, 307):
                    text_sample = (await resp.text())[:300]
                    _LOGGER.warning(
                        "CIAM Step 6 failed: Token exchange returned HTTP %s. Body: %s",
                        resp.status,
                        text_sample,
                    )
                    raise DHLAuthError(
                        f"Code exchange failed with status {resp.status}"
                    )

            # Extract cookies from cookie jar
            cookie_jar = self._session.cookie_jar.filter_cookies(
                f"https://{DHL_PORTAL_HOST}"
            )
            dhla0 = cookie_jar.get("dhla0")
            dhlr0 = cookie_jar.get("dhlr0")
            dhlb = cookie_jar.get("dhlb")
            verfolgen_csrf = cookie_jar.get("verfolgenCsrfToken")

            if not dhla0 or not dhlr0 or not dhlb:
                _LOGGER.warning(
                    "Missing expected cookies in jar after login. Found: %s",
                    list(cookie_jar.keys()),
                )
                raise DHLAuthError(
                    "Missing session cookies (dhla0, dhlr0, dhlb) after login"
                )

            dhla0_val = dhla0.value
            dhlr0_val = dhlr0.value
            dhlb_val = dhlb.value
            csrf_val = verfolgen_csrf.value if verfolgen_csrf else secrets.token_hex(16)

            payload = _decode_jwt_payload(dhla0_val)
            email = str(payload.get("email") or username)
            post_number = str(payload.get("post_number") or "")
            display_name = str(payload.get("display_name") or email)
            expires_at = float(payload.get("exp") or (time.time() + 1800))

            creds = DHLCredentials(
                email=email,
                post_number=post_number,
                display_name=display_name,
                dhla0=dhla0_val,
                dhlr0=dhlr0_val,
                dhlb=dhlb_val,
                verfolgen_csrf=csrf_val,
                expires_at=expires_at,
            )
            self.credentials = creds
            _LOGGER.debug(
                "DHL CIAM login succeeded for %s (post_number: %s, token expires in %.1f min)",
                _mask_identifier(creds.email),
                _mask_identifier(creds.post_number),
                (creds.expires_at - time.time()) / 60,
            )
            return creds

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Connection error during DHL login: %s", err)
            raise DHLConnectionError(f"Connection error during login: {err}") from err

    async def async_login_with_cookies(
        self,
        dhla0: str,
        dhlr0: str,
        dhlb: str,
        verfolgen_csrf: str | None = None,
        email_override: str | None = None,
    ) -> DHLCredentials:
        """Configure client directly with session cookies."""
        _LOGGER.debug(
            "Configuring DHL client with session cookies (dhla0: %s, dhlr0: %s, dhlb: %s, csrf: %s)",
            _mask_token(dhla0),
            _mask_token(dhlr0),
            _mask_token(dhlb),
            _mask_token(verfolgen_csrf),
        )
        dhla0_clean = dhla0.strip()
        dhlr0_clean = dhlr0.strip()
        dhlb_clean = dhlb.strip()
        csrf_clean = (
            verfolgen_csrf.strip()
            if (verfolgen_csrf and verfolgen_csrf.strip())
            else secrets.token_hex(16)
        )

        payload = _decode_jwt_payload(dhla0_clean)
        email = (
            email_override.strip()
            if (email_override and email_override.strip())
            else str(payload.get("email") or "")
        )
        post_number = str(payload.get("post_number") or "")
        display_name = str(payload.get("display_name") or email)
        expires_at = float(payload.get("exp") or (time.time() + 1800))

        creds = DHLCredentials(
            email=email,
            post_number=post_number,
            display_name=display_name,
            dhla0=dhla0_clean,
            dhlr0=dhlr0_clean,
            dhlb=dhlb_clean,
            verfolgen_csrf=csrf_clean,
            expires_at=expires_at,
        )
        self.credentials = creds

        _LOGGER.debug(
            "Session cookies loaded for %s (post_number: %s, token expires in %.1f min). Validating with tracking API...",
            _mask_identifier(email),
            _mask_identifier(post_number),
            (expires_at - time.time()) / 60,
        )

        # Validate by making test request
        await self.async_validate()
        return creds

    async def async_refresh_tokens(self) -> bool:
        """Refresh active session tokens via multipart/form-data call."""
        if not self.credentials:
            raise DHLAuthError("Cannot refresh: no credentials configured")

        _LOGGER.debug(
            "Refreshing DHL session tokens for %s (current token: %s)",
            _mask_identifier(self.credentials.email),
            _mask_token(self.credentials.dhla0),
        )
        form = aiohttp.FormData()
        form.add_field("bForceRefresh", "true")
        form.add_field("bAfterMasterDataChange", "false")

        cookies = {
            "dhla0": self.credentials.dhla0,
            "dhlr0": self.credentials.dhlr0,
            "dhlb": self.credentials.dhlb,
        }
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://{DHL_PORTAL_HOST}/",
        }

        try:
            async with self._session.post(
                API_REFRESH_URL,
                data=form,
                cookies=cookies,
                headers=headers,
            ) as resp:
                if resp.status in (401, 403):
                    text_sample = (await resp.text())[:200]
                    _LOGGER.warning(
                        "Session refresh rejected with status %s: %s",
                        resp.status,
                        text_sample,
                    )
                    raise DHLAuthError(
                        f"Session refresh rejected with status {resp.status}"
                    )
                if resp.status != 200:
                    _LOGGER.warning(
                        "Session refresh returned unexpected status: %s",
                        resp.status,
                    )
                    return False

                # Parse JSON response body if available
                try:
                    data = await resp.json()
                    if isinstance(data, dict):
                        if data.get("status") != 0 or data.get("akamaiError"):
                            err_detail = (data.get("akamaiError") or {}).get(
                                "detail"
                            ) or f"status={data.get('status')}"
                            _LOGGER.warning(
                                "DHL token refresh rejected by backend (%s)",
                                err_detail,
                            )
                            raise DHLAuthError(
                                f"DHL session refresh rejected: {err_detail}"
                            )
                        user_info = data.get("userInfo") or {}
                        if (expiry := user_info.get("expiryDate")) and float(
                            expiry
                        ) > 0:
                            self.credentials.expires_at = float(expiry)
                except (json.JSONDecodeError, ValueError, aiohttp.ContentTypeError):
                    _LOGGER.debug(
                        "Could not parse JSON response during session refresh"
                    )

                # Check for updated cookies
                new_dhla0 = resp.cookies.get("dhla0")
                new_dhlr0 = resp.cookies.get("dhlr0")
                new_dhlb = resp.cookies.get("dhlb")

                if new_dhla0 and len(new_dhla0.value.split(".")) >= 2:
                    self.credentials.dhla0 = new_dhla0.value
                    payload = _decode_jwt_payload(new_dhla0.value)
                    if exp := payload.get("exp"):
                        self.credentials.expires_at = float(exp)
                if new_dhlr0 and new_dhlr0.value:
                    self.credentials.dhlr0 = new_dhlr0.value
                if new_dhlb and new_dhlb.value:
                    self.credentials.dhlb = new_dhlb.value

                _LOGGER.debug(
                    "DHL session tokens refreshed successfully for %s (new expiry in %.1f min)",
                    _mask_identifier(self.credentials.email),
                    (self.credentials.expires_at - time.time()) / 60,
                )
                return True
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Connection error during DHL token refresh: %s", err)
            raise DHLConnectionError(
                f"Connection error during token refresh: {err}"
            ) from err

    async def async_get_shipments(self) -> list[Parcel]:
        """Fetch all shipment parcels for the authenticated account."""
        if not self.credentials:
            raise DHLAuthError("Authentication credentials not configured")

        _LOGGER.debug(
            "Fetching DHL shipments for %s (token expires in %.1f min)",
            _mask_identifier(self.credentials.email or self.credentials.post_number),
            (self.credentials.expires_at - time.time()) / 60,
        )
        url = f"{API_SEARCH_URL}?noRedirect=true&language=de"
        headers = {
            "Accept": "application/json",
            "Verfolgen-Csrf-Token": self.credentials.verfolgen_csrf,
            "Verfolgen-Wg": "3",
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": f"https://{DHL_PORTAL_HOST}/de/privatkunden/pakete-empfangen/verfolgen.html",
        }
        cookies = {
            "dhla0": self.credentials.dhla0,
            "dhlr0": self.credentials.dhlr0,
            "dhlb": self.credentials.dhlb,
            "verfolgenCsrfToken": self.credentials.verfolgen_csrf,
        }

        try:
            async with self._session.get(
                url,
                headers=headers,
                cookies=cookies,
            ) as resp:
                _LOGGER.debug("DHL tracking API returned HTTP %s", resp.status)
                if resp.status in (401, 403):
                    text_sample = (await resp.text())[:300]
                    _LOGGER.warning(
                        "DHL tracking request rejected (HTTP %s). Cookies may be invalid, expired, or blocked by bot protection. Response preview: %s",
                        resp.status,
                        text_sample,
                    )
                    raise DHLAuthError(
                        f"DHL authentication expired or invalid (HTTP {resp.status})"
                    )
                if resp.status == 429:
                    _LOGGER.warning("DHL tracking request hit rate limit (HTTP 429)")
                    raise DHLRateLimitError("DHL tracking API rate limit exceeded")
                if resp.status != 200:
                    text_sample = (await resp.text())[:300]
                    _LOGGER.warning(
                        "DHL tracking API returned unexpected status %s: %s",
                        resp.status,
                        text_sample,
                    )
                    raise DHLError(
                        f"DHL tracking API returned unexpected status {resp.status}"
                    )

                data = await resp.json()

                if data.get("rateLimited"):
                    _LOGGER.warning(
                        "DHL reported rate limiting flag in response payload"
                    )
                    raise DHLRateLimitError(
                        "DHL reported rate limiting in response payload"
                    )

                sendungen = data.get("sendungen") or []
                parcels: list[Parcel] = []
                for item in sendungen:
                    if isinstance(item, dict):
                        # Try to resolve email from parcel details if missing
                        if not self.credentials.email:
                            details = item.get("sendungsdetails") or {}
                            if parcel_email := details.get("email"):
                                self.credentials.email = str(parcel_email)

                        try:
                            parcels.append(Parcel.from_api_dict(item))
                        except (KeyError, TypeError, ValueError) as err:
                            _LOGGER.warning("Failed to parse parcel item: %s", err)

                _LOGGER.debug(
                    "Successfully fetched %d DHL shipments (%d active, %d delivered)",
                    len(parcels),
                    sum(1 for p in parcels if not p.is_delivered),
                    sum(1 for p in parcels if p.is_delivered),
                )
                return parcels
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Connection error while fetching DHL shipments: %s", err)
            raise DHLConnectionError(
                f"Connection error while fetching shipments: {err}"
            ) from err

    async def async_validate(self) -> tuple[str, str]:
        """Validate credentials against DHL API and return (email, post_number)."""
        if not self.credentials:
            raise DHLAuthError("No credentials configured for validation")

        # Test request to ensure cookies and permissions work
        _LOGGER.debug("Validating DHL credentials via test API request...")
        await self.async_get_shipments()

        email = self.credentials.email or ""
        post_number = self.credentials.post_number or ""
        _LOGGER.debug(
            "Validation successful for %s (post_number: %s)",
            _mask_identifier(email),
            _mask_identifier(post_number),
        )
        return email, post_number
