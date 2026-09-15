"""Diagnostics support for the DHL integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DHLConfigEntry
from .const import (
    CONF_DHLA0,
    CONF_DHLB,
    CONF_DHLR0,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POST_NUMBER,
    CONF_USERNAME,
    CONF_VERFOLGEN_CSRF,
)

TO_REDACT = {
    CONF_DHLA0,
    CONF_DHLR0,
    CONF_DHLB,
    CONF_VERFOLGEN_CSRF,
    CONF_PASSWORD,
    CONF_EMAIL,
    CONF_POST_NUMBER,
    CONF_USERNAME,
    "email",
    "password",
    "post_number",
    "dhla0",
    "dhlr0",
    "dhlb",
    "verfolgen_csrf",
    "username",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: DHLConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a DHL config entry."""
    coordinator = entry.runtime_data.coordinator
    client = entry.runtime_data.client

    # Summarize parcels with partially redacted tracking numbers
    parcels_summary: list[dict[str, Any]] = []
    for parcel in coordinator.all_parcels:
        tracking = parcel.tracking_number
        redacted_tracking = (
            f"{tracking[:4]}****{tracking[-4:]}" if len(tracking) > 8 else "****"
        )
        parcels_summary.append(
            {
                "id": parcel.id,
                "tracking_number": redacted_tracking,
                "name": parcel.name,
                "direction": str(parcel.direction),
                "list_type": parcel.list_type,
                "is_delivered": parcel.is_delivered,
                "status_text": parcel.status_text,
                "has_progress": parcel.progress is not None,
                "current_step": (
                    parcel.progress.current_step if parcel.progress else None
                ),
                "max_steps": parcel.progress.max_steps if parcel.progress else None,
                "events_count": (len(parcel.progress.events) if parcel.progress else 0),
                "expected_delivery_date": parcel.expected_delivery_date,
            }
        )

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "pref_disable_new_entities": entry.pref_disable_new_entities,
            "pref_disable_polling": entry.pref_disable_polling,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_poll_time": (
                coordinator.last_poll_time.isoformat()
                if coordinator.last_poll_time
                else None
            ),
            "data_count": len(coordinator.data),
            "all_parcels_count": len(coordinator.all_parcels),
        },
        "client": {
            "has_credentials": client.credentials is not None,
            "expires_at": (
                client.credentials.expires_at if client.credentials else None
            ),
            "expires_soon": client.expires_soon(within_seconds=300),
        },
        "parcels_summary": parcels_summary,
    }
