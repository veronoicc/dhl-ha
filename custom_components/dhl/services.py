"""Services for the DHL integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_GET_PARCELS,
    SERVICE_REFRESH_PARCELS,
)
from .models import ParcelDirection, ParcelListType

_LOGGER = logging.getLogger(__name__)

SERVICES_REGISTERED_KEY = f"{DOMAIN}_services_registered"

CONF_CONFIG_ENTRY_ID = "config_entry_id"
CONF_STATUS_FILTER = "status_filter"
CONF_INCLUDE_ARCHIVED = "include_archived"

STATUS_FILTER_ALL = "all"
STATUS_FILTER_IN_TRANSIT = "in_transit"
STATUS_FILTER_DELIVERED = "delivered"
STATUS_FILTER_INCOMING = "incoming"
STATUS_FILTER_OUTGOING = "outgoing"

VALID_STATUS_FILTERS = [
    STATUS_FILTER_ALL,
    STATUS_FILTER_IN_TRANSIT,
    STATUS_FILTER_DELIVERED,
    STATUS_FILTER_INCOMING,
    STATUS_FILTER_OUTGOING,
]

GET_PARCELS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_STATUS_FILTER, default=STATUS_FILTER_ALL): vol.In(
            VALID_STATUS_FILTERS
        ),
        vol.Optional(CONF_INCLUDE_ARCHIVED, default=False): cv.boolean,
    }
)

REFRESH_PARCELS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register DHL service actions."""
    if hass.data.get(SERVICES_REGISTERED_KEY):
        return

    async def async_handle_get_parcels(call: ServiceCall) -> dict[str, Any]:
        """Return parcel list matching query parameters."""
        target_entry_id = call.data.get(CONF_CONFIG_ENTRY_ID)
        status_filter = call.data.get(CONF_STATUS_FILTER, STATUS_FILTER_ALL)
        include_archived = call.data.get(CONF_INCLUDE_ARCHIVED, False)
        _LOGGER.debug(
            "Service action dhl.get_parcels called (target: %s, filter: %s, archived: %s)",
            target_entry_id or "ALL",
            status_filter,
            include_archived,
        )

        loaded_entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not loaded_entries:
            raise ServiceValidationError("No DHL accounts are currently loaded")

        if target_entry_id:
            entries = [e for e in loaded_entries if e.entry_id == target_entry_id]
            if not entries:
                raise ServiceValidationError(
                    f"DHL account entry '{target_entry_id}' not found or not loaded"
                )
        else:
            entries = loaded_entries

        all_matching_parcels: list[dict[str, Any]] = []

        for entry in entries:
            coordinator = entry.runtime_data.coordinator
            raw_parcels = (
                coordinator.all_parcels if include_archived else coordinator.data
            )

            for parcel in raw_parcels:
                if (
                    not include_archived
                    and parcel.list_type == ParcelListType.ARCHIVIERT
                ):
                    continue

                if status_filter == STATUS_FILTER_IN_TRANSIT and (
                    parcel.is_delivered or parcel.is_archived
                ):
                    continue
                if status_filter == STATUS_FILTER_DELIVERED and not parcel.is_delivered:
                    continue
                if (
                    status_filter == STATUS_FILTER_INCOMING
                    and parcel.direction != ParcelDirection.ANKOMMEND
                ):
                    continue
                if (
                    status_filter == STATUS_FILTER_OUTGOING
                    and parcel.direction != ParcelDirection.ABGEHEND
                ):
                    continue

                parcel_dict = parcel.to_dict()
                parcel_dict["account_title"] = entry.title
                parcel_dict["config_entry_id"] = entry.entry_id
                all_matching_parcels.append(parcel_dict)

        _LOGGER.debug(
            "Service action dhl.get_parcels returning %d parcels across %d accounts",
            len(all_matching_parcels),
            len(entries),
        )
        return {"parcels": all_matching_parcels}

    async def async_handle_refresh_parcels(call: ServiceCall) -> None:
        """Trigger immediate data refresh from DHL API."""
        target_entry_id = call.data.get(CONF_CONFIG_ENTRY_ID)
        _LOGGER.debug(
            "Service action dhl.refresh_parcels called (target: %s)",
            target_entry_id or "ALL",
        )
        loaded_entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not loaded_entries:
            raise ServiceValidationError("No DHL accounts are currently loaded")

        if target_entry_id:
            entries = [e for e in loaded_entries if e.entry_id == target_entry_id]
            if not entries:
                raise ServiceValidationError(
                    f"DHL account entry '{target_entry_id}' not found or not loaded"
                )
        else:
            entries = loaded_entries

        refresh_tasks = [
            entry.runtime_data.coordinator.async_request_refresh() for entry in entries
        ]
        await asyncio.gather(*refresh_tasks)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PARCELS,
        async_handle_get_parcels,
        schema=GET_PARCELS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_PARCELS,
        async_handle_refresh_parcels,
        schema=REFRESH_PARCELS_SCHEMA,
    )

    hass.data[SERVICES_REGISTERED_KEY] = True


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload DHL service actions."""
    if not hass.data.get(SERVICES_REGISTERED_KEY):
        return

    hass.services.async_remove(DOMAIN, SERVICE_GET_PARCELS)
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH_PARCELS)
    hass.data[SERVICES_REGISTERED_KEY] = False
