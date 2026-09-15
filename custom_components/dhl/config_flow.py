"""Config flow for the DHL integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)

try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:  # pragma: no cover
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult

from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    DHLAuthError,
    DHLClient,
    DHLConnectionError,
    DHLError,
    DHLRateLimitError,
    _mask_identifier,
)
from .const import (
    AUTH_METHOD_COOKIES,
    AUTH_METHOD_CREDENTIALS,
    CONF_AUTH_METHOD,
    CONF_DHLA0,
    CONF_DHLB,
    CONF_DHLR0,
    CONF_EMAIL,
    CONF_INCLUDE_ARCHIVED,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_POST_NUMBER,
    CONF_USERNAME,
    CONF_VERFOLGEN_CSRF,
    DEFAULT_INCLUDE_ARCHIVED,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class DHLConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DHL."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._auth_method: str = AUTH_METHOD_CREDENTIALS
        self._reauth_entry: ConfigEntry | None = None
        self._reconfigure_entry: ConfigEntry | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 1: choose authentication method."""
        if user_input is not None:
            self._auth_method = user_input[CONF_AUTH_METHOD]
            if self._auth_method == AUTH_METHOD_CREDENTIALS:
                return await self.async_step_credentials()
            return await self.async_step_cookies()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AUTH_METHOD,
                    default=AUTH_METHOD_CREDENTIALS,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            AUTH_METHOD_CREDENTIALS,
                            AUTH_METHOD_COOKIES,
                        ],
                        translation_key="auth_method",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_credentials(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 2a: input credentials and authenticate via CIAM."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = DHLClient(session)

            try:
                creds = await client.async_login(username, password)
                email, post_number = await client.async_validate()
            except DHLAuthError as err:
                _LOGGER.warning(
                    "DHL credentials authentication failed for %s: %s",
                    _mask_identifier(username),
                    err,
                )
                errors["base"] = "invalid_auth"
            except DHLConnectionError as err:
                _LOGGER.warning(
                    "DHL connection error during login for %s: %s",
                    _mask_identifier(username),
                    err,
                )
                errors["base"] = "cannot_connect"
            except DHLRateLimitError as err:
                _LOGGER.warning(
                    "DHL rate limit exceeded during login for %s: %s",
                    _mask_identifier(username),
                    err,
                )
                errors["base"] = "rate_limited"
            except DHLError as err:
                _LOGGER.warning(
                    "DHL error during login for %s: %s", _mask_identifier(username), err
                )
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception(
                    "Unexpected exception during DHL credentials login for %s",
                    _mask_identifier(username),
                )
                errors["base"] = "unknown"
            else:
                unique_id = post_number if post_number else email
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = f"DHL ({email})" if email else f"DHL ({unique_id})"
                _LOGGER.info(
                    "Configured new DHL account '%s' (post_number: %s)",
                    title,
                    _mask_identifier(post_number),
                )
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_CREDENTIALS,
                        CONF_EMAIL: email,
                        CONF_POST_NUMBER: post_number,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_DHLA0: creds.dhla0,
                        CONF_DHLR0: creds.dhlr0,
                        CONF_DHLB: creds.dhlb,
                        CONF_VERFOLGEN_CSRF: creds.verfolgen_csrf,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.EMAIL,
                        autocomplete="username",
                    )
                ),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="current-password",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="credentials",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_cookies(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step 2b: input session cookies directly."""
        errors: dict[str, str] = {}

        if user_input is not None:
            dhla0 = user_input[CONF_DHLA0].strip()
            dhlr0 = user_input[CONF_DHLR0].strip()
            dhlb = user_input[CONF_DHLB].strip()
            verfolgen_csrf = user_input.get(CONF_VERFOLGEN_CSRF, "").strip()

            session = async_get_clientsession(self.hass)
            client = DHLClient(session)

            try:
                creds = await client.async_login_with_cookies(
                    dhla0, dhlr0, dhlb, verfolgen_csrf
                )
                email, post_number = await client.async_validate()
            except DHLAuthError as err:
                _LOGGER.warning("DHL cookie authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except DHLConnectionError as err:
                _LOGGER.warning("DHL connection error during cookie login: %s", err)
                errors["base"] = "cannot_connect"
            except DHLRateLimitError as err:
                _LOGGER.warning("DHL rate limit exceeded during cookie login: %s", err)
                errors["base"] = "rate_limited"
            except DHLError as err:
                _LOGGER.warning("DHL error during cookie login: %s", err)
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected exception during DHL cookie login")
                errors["base"] = "unknown"
            else:
                unique_id = post_number if post_number else email
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = f"DHL ({email})" if email else f"DHL ({unique_id})"
                _LOGGER.info(
                    "Configured new DHL account via cookies '%s' (post_number: %s)",
                    title,
                    _mask_identifier(post_number),
                )
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_COOKIES,
                        CONF_EMAIL: email,
                        CONF_POST_NUMBER: post_number,
                        CONF_DHLA0: creds.dhla0,
                        CONF_DHLR0: creds.dhlr0,
                        CONF_DHLB: creds.dhlb,
                        CONF_VERFOLGEN_CSRF: creds.verfolgen_csrf,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_DHLA0): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_DHLR0): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_DHLB): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_VERFOLGEN_CSRF): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
            }
        )

        return self.async_show_form(
            step_id="cookies",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Handle reauthorization upon session expiration."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm and process re-authentication."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        auth_method = self._reauth_entry.data.get(
            CONF_AUTH_METHOD, AUTH_METHOD_CREDENTIALS
        )
        existing_username = self._reauth_entry.data.get(CONF_USERNAME, "")
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = DHLClient(session)

            try:
                if auth_method == AUTH_METHOD_CREDENTIALS:
                    username = user_input.get(
                        CONF_USERNAME,
                        self._reauth_entry.data.get(CONF_USERNAME, ""),
                    )
                    password = user_input[CONF_PASSWORD]
                    creds = await client.async_login(username, password)
                    new_data = {
                        **self._reauth_entry.data,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_DHLA0: creds.dhla0,
                        CONF_DHLR0: creds.dhlr0,
                        CONF_DHLB: creds.dhlb,
                        CONF_VERFOLGEN_CSRF: creds.verfolgen_csrf,
                    }
                else:
                    dhla0 = user_input[CONF_DHLA0].strip()
                    dhlr0 = user_input[CONF_DHLR0].strip()
                    dhlb = user_input[CONF_DHLB].strip()
                    verfolgen_csrf = user_input.get(CONF_VERFOLGEN_CSRF, "").strip()
                    creds = await client.async_login_with_cookies(
                        dhla0, dhlr0, dhlb, verfolgen_csrf
                    )
                    new_data = {
                        **self._reauth_entry.data,
                        CONF_DHLA0: creds.dhla0,
                        CONF_DHLR0: creds.dhlr0,
                        CONF_DHLB: creds.dhlb,
                        CONF_VERFOLGEN_CSRF: creds.verfolgen_csrf,
                    }

                await client.async_validate()
            except DHLAuthError as err:
                _LOGGER.warning(
                    "DHL re-authentication failed for '%s': %s",
                    self._reauth_entry.title,
                    err,
                )
                errors["base"] = "invalid_auth"
            except DHLConnectionError as err:
                _LOGGER.warning(
                    "DHL connection error during reauth for '%s': %s",
                    self._reauth_entry.title,
                    err,
                )
                errors["base"] = "cannot_connect"
            except DHLRateLimitError as err:
                _LOGGER.warning(
                    "DHL rate limit exceeded during reauth for '%s': %s",
                    self._reauth_entry.title,
                    err,
                )
                errors["base"] = "rate_limited"
            except (DHLError, Exception):
                _LOGGER.exception(
                    "Unexpected exception during DHL re-authentication for '%s'",
                    self._reauth_entry.title,
                )
                errors["base"] = "unknown"
            else:
                _LOGGER.info(
                    "Successfully re-authenticated DHL account '%s'",
                    self._reauth_entry.title if self._reauth_entry else "DHL",
                )
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data=new_data,
                )

        if auth_method == AUTH_METHOD_CREDENTIALS:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=existing_username
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.EMAIL,
                            autocomplete="username",
                        )
                    ),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_DHLA0): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_DHLR0): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_DHLB): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_VERFOLGEN_CSRF): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration of integration parameters."""
        self._reconfigure_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        assert self._reconfigure_entry is not None

        errors: dict[str, str] = {}
        auth_method = self._reconfigure_entry.data.get(
            CONF_AUTH_METHOD, AUTH_METHOD_CREDENTIALS
        )
        existing_username = self._reconfigure_entry.data.get(CONF_USERNAME, "")
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = DHLClient(session)

            try:
                if auth_method == AUTH_METHOD_CREDENTIALS:
                    username = user_input[CONF_USERNAME].strip()
                    password = user_input[CONF_PASSWORD]
                    creds = await client.async_login(username, password)
                    new_data = {
                        **self._reconfigure_entry.data,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_DHLA0: creds.dhla0,
                        CONF_DHLR0: creds.dhlr0,
                        CONF_DHLB: creds.dhlb,
                        CONF_VERFOLGEN_CSRF: creds.verfolgen_csrf,
                    }
                else:
                    dhla0 = user_input[CONF_DHLA0].strip()
                    dhlr0 = user_input[CONF_DHLR0].strip()
                    dhlb = user_input[CONF_DHLB].strip()
                    verfolgen_csrf = user_input.get(CONF_VERFOLGEN_CSRF, "").strip()
                    creds = await client.async_login_with_cookies(
                        dhla0, dhlr0, dhlb, verfolgen_csrf
                    )
                    new_data = {
                        **self._reconfigure_entry.data,
                        CONF_DHLA0: creds.dhla0,
                        CONF_DHLR0: creds.dhlr0,
                        CONF_DHLB: creds.dhlb,
                        CONF_VERFOLGEN_CSRF: creds.verfolgen_csrf,
                    }

                await client.async_validate()
            except DHLAuthError as err:
                _LOGGER.warning(
                    "DHL reconfiguration failed for '%s': %s",
                    self._reconfigure_entry.title,
                    err,
                )
                errors["base"] = "invalid_auth"
            except DHLConnectionError as err:
                _LOGGER.warning(
                    "DHL connection error during reconfigure for '%s': %s",
                    self._reconfigure_entry.title,
                    err,
                )
                errors["base"] = "cannot_connect"
            except DHLRateLimitError as err:
                _LOGGER.warning(
                    "DHL rate limit exceeded during reconfigure for '%s': %s",
                    self._reconfigure_entry.title,
                    err,
                )
                errors["base"] = "rate_limited"
            except (DHLError, Exception):
                _LOGGER.exception(
                    "Unexpected exception during DHL reconfiguration for '%s'",
                    self._reconfigure_entry.title,
                )
                errors["base"] = "unknown"
            else:
                _LOGGER.info(
                    "Successfully reconfigured DHL account '%s'",
                    self._reconfigure_entry.title if self._reconfigure_entry else "DHL",
                )
                return self.async_update_reload_and_abort(
                    self._reconfigure_entry,
                    data=new_data,
                )

        if auth_method == AUTH_METHOD_CREDENTIALS:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=existing_username
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.EMAIL,
                            autocomplete="username",
                        )
                    ),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_DHLA0): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_DHLR0): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_DHLB): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_VERFOLGEN_CSRF): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow handler."""
        return DHLOptionsFlowHandler(config_entry)


class DHLOptionsFlowHandler(OptionsFlow):
    """Handle options for DHL integration."""

    def __init__(self, config_entry: ConfigEntry | None = None) -> None:
        """Initialize DHL options flow."""
        if config_entry is not None:
            self.config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage options for DHL."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_POLL_INTERVAL,
            self.config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )
        current_archived = self.config_entry.options.get(
            CONF_INCLUDE_ARCHIVED,
            DEFAULT_INCLUDE_ARCHIVED,
        )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=current_interval,
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_INCLUDE_ARCHIVED,
                    default=current_archived,
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
