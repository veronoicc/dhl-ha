"""The DHL integration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DHLClient, DHLCredentials, _decode_jwt_payload
from .const import (
    CONF_DHLA0,
    CONF_DHLB,
    CONF_DHLR0,
    CONF_EMAIL,
    CONF_POST_NUMBER,
    CONF_VERFOLGEN_CSRF,
    DHL_PORTAL_HOST,
    DOMAIN,
)
from .coordinator import DHLDataUpdateCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.TODO,
]


@dataclass
class DHLData:
    """Runtime data stored in ConfigEntry."""

    client: DHLClient
    coordinator: DHLDataUpdateCoordinator


type DHLConfigEntry = ConfigEntry[DHLData]


async def async_setup_entry(hass: HomeAssistant, entry: DHLConfigEntry) -> bool:
    """Set up DHL from a config entry."""
    _LOGGER.debug(
        "Setting up DHL entry '%s' (entry_id: %s)", entry.title, entry.entry_id
    )
    session = async_get_clientsession(hass)
    dhla0 = entry.data.get(CONF_DHLA0, "")
    dhlr0 = entry.data.get(CONF_DHLR0, "")
    dhlb = entry.data.get(CONF_DHLB, "")
    verfolgen_csrf = entry.data.get(CONF_VERFOLGEN_CSRF, "")
    email = entry.data.get(CONF_EMAIL, "")
    post_number = entry.data.get(CONF_POST_NUMBER, "")

    # Decode JWT to get expiration and name if available
    payload = _decode_jwt_payload(dhla0)
    display_name = str(payload.get("display_name") or email or entry.title)
    expires_at = float(payload.get("exp") or (time.time() + 1800))

    if not email and (jwt_email := payload.get("email")):
        email = str(jwt_email)
    if not post_number and (jwt_post := payload.get("post_number")):
        post_number = str(jwt_post)

    credentials = DHLCredentials(
        email=email,
        post_number=post_number,
        display_name=display_name,
        dhla0=dhla0,
        dhlr0=dhlr0,
        dhlb=dhlb,
        verfolgen_csrf=verfolgen_csrf,
        expires_at=expires_at,
    )

    client = DHLClient(session, credentials=credentials)
    coordinator = DHLDataUpdateCoordinator(hass, entry, client)

    # Initial data refresh before platform setup
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.debug(
        "Initial refresh successful for '%s': %d active parcels (%d total)",
        entry.title,
        len(coordinator.data),
        len(coordinator.all_parcels),
    )

    entry.runtime_data = DHLData(
        client=client,
        coordinator=coordinator,
    )
    # Register device in Home Assistant Device Registry
    device_registry = dr.async_get(hass)
    device_identifier = entry.unique_id or entry.entry_id
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_identifier)},
        name=entry.title,
        manufacturer="DHL",
        model="Web Internal API",
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=f"https://{DHL_PORTAL_HOST}",
    )

    # Register service actions
    await async_setup_services(hass)
    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload on options update
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _LOGGER.info("DHL integration setup completed for '%s'", entry.title)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DHLConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug(
        "Unloading DHL entry '%s' (entry_id: %s)", entry.title, entry.entry_id
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await async_unload_services(hass)
        _LOGGER.info("Successfully unloaded DHL entry '%s'", entry.title)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: DHLConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.debug(
        "Reloading DHL entry '%s' (entry_id: %s)", entry.title, entry.entry_id
    )
    await hass.config_entries.async_reload(entry.entry_id)
