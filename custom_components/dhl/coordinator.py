"""DataUpdateCoordinator for DHL parcel tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DHLAuthError, DHLClient, DHLConnectionError, DHLRateLimitError
from .const import (
    CONF_DHLA0,
    CONF_DHLB,
    CONF_DHLR0,
    CONF_INCLUDE_ARCHIVED,
    CONF_POLL_INTERVAL,
    DEFAULT_INCLUDE_ARCHIVED,
    DEFAULT_POLL_INTERVAL,
)
from .models import Parcel, ParcelListType

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class DHLDataUpdateCoordinator(DataUpdateCoordinator[list[Parcel]]):
    """Coordinator to fetch parcel tracking updates from DHL."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DHLClient,
    ) -> None:
        """Initialize DHL coordinator."""
        self.entry = entry
        self.client = client
        self.all_parcels: list[Parcel] = []
        self.last_poll_time: datetime | None = None

        poll_minutes = entry.options.get(
            CONF_POLL_INTERVAL,
            entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(minutes=max(5, int(poll_minutes))),
        )

    async def _async_update_data(self) -> list[Parcel]:
        """Fetch and process DHL shipments."""
        # 1. Proactively refresh token if close to expiry
        if self.client.expires_soon(within_seconds=300):
            _LOGGER.debug(
                "DHL token expiring soon for '%s', proactively refreshing",
                self.entry.title,
            )
            try:
                refreshed = await self.client.async_refresh_tokens()
                if refreshed and self.client.credentials:
                    self.hass.config_entries.async_update_entry(
                        self.entry,
                        data={
                            **self.entry.data,
                            CONF_DHLA0: self.client.credentials.dhla0,
                            CONF_DHLR0: self.client.credentials.dhlr0,
                            CONF_DHLB: self.client.credentials.dhlb,
                        },
                    )
            except DHLAuthError as err:
                _LOGGER.error(
                    "DHL session refresh failed for '%s': %s (re-authentication required)",
                    self.entry.title,
                    err,
                )
                raise ConfigEntryAuthFailed(
                    "DHL session expired, reauthentication required"
                ) from err
            except DHLConnectionError as err:
                _LOGGER.warning(
                    "Connection error while refreshing DHL token for '%s': %s",
                    self.entry.title,
                    err,
                )

        # 2. Fetch shipments
        try:
            parcels = await self.client.async_get_shipments()
        except DHLAuthError as err:
            _LOGGER.error("DHL authentication failed for '%s'", self.entry.title)
            raise ConfigEntryAuthFailed("DHL authentication failed") from err
        except DHLRateLimitError as err:
            _LOGGER.warning("DHL rate limit exceeded for '%s'", self.entry.title)
            raise UpdateFailed(f"DHL rate limit exceeded: {err}") from err
        except DHLConnectionError as err:
            _LOGGER.warning("DHL connection error for '%s': %s", self.entry.title, err)
            raise UpdateFailed(f"Failed to fetch DHL shipments: {err}") from err
        self.last_poll_time = dt_util.utcnow()
        self.all_parcels = parcels

        include_archived = self.entry.options.get(
            CONF_INCLUDE_ARCHIVED,
            self.entry.data.get(CONF_INCLUDE_ARCHIVED, DEFAULT_INCLUDE_ARCHIVED),
        )

        active_parcels = [
            p for p in parcels if p.list_type != ParcelListType.ARCHIVIERT
        ]
        _LOGGER.debug(
            "Coordinator update completed for '%s': %d active parcels (%d total)",
            self.entry.title,
            len(active_parcels),
            len(parcels),
        )

        if not include_archived:
            return active_parcels

        return parcels
