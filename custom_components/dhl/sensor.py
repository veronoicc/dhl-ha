"""Sensor platform for DHL parcel tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DHLConfigEntry
from .const import CONF_INCLUDE_ARCHIVED, DEFAULT_INCLUDE_ARCHIVED, DOMAIN
from .coordinator import DHLDataUpdateCoordinator
from .models import Parcel, ParcelDirection


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DHLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHL sensor entities from a config entry."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities(
        [
            DHLParcelInTransitSensor(coordinator, entry),
            DHLParcelDeliveredSensor(coordinator, entry),
            DHLParcelIncomingSensor(coordinator, entry),
            DHLParcelOutgoingSensor(coordinator, entry),
            DHLParcelArchivedSensor(coordinator, entry),
            DHLParcelTotalSensor(coordinator, entry),
            DHLLastUpdateSensor(coordinator, entry),
        ]
    )


class DHLBaseSensor(CoordinatorEntity[DHLDataUpdateCoordinator], SensorEntity):
    """Base class for DHL sensor entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
        sensor_key: str,
    ) -> None:
        """Initialize base DHL sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self.sensor_key = sensor_key

        unique_base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_base}_{sensor_key}"
        self._attr_translation_key = sensor_key

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information linking to the DHL account."""
        unique_base = self.entry.unique_id or self.entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, unique_base)},
            name=self.entry.title,
            manufacturer="DHL",
            model="Kundenkonto",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _parcel_detail_dict(self, parcel: Parcel) -> dict[str, Any]:
        """Format detailed parcel dictionary for attributes."""
        last_event_time = None
        last_event_status = None
        if parcel.progress and parcel.progress.events:
            last_event = parcel.progress.events[-1]
            last_event_time = last_event.datum
            last_event_status = last_event.status

        return {
            "id": parcel.id,
            "tracking_number": parcel.tracking_number,
            "name": parcel.name,
            "direction": str(parcel.direction),
            "status": parcel.status_text,
            "is_delivered": parcel.is_delivered,
            "list_type": parcel.list_type,
            "expected_delivery_date": parcel.expected_delivery_date,
            "current_step": parcel.progress.current_step if parcel.progress else None,
            "max_steps": parcel.progress.max_steps if parcel.progress else None,
            "last_event_time": last_event_time,
            "last_event_status": last_event_status,
            "recipient_name": parcel.recipient.name if parcel.recipient else None,
            "recipient_city": parcel.recipient.city if parcel.recipient else None,
            "pickup_code_available": (
                parcel.delivery.abholcode_available if parcel.delivery else False
            ),
        }


class DHLParcelInTransitSensor(DHLBaseSensor):
    """Sensor tracking the count of active parcels currently in transit."""

    _attr_icon = "mdi:package-variant-closed"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize in-transit parcels sensor."""
        super().__init__(coordinator, entry, "in_transit")

    @property
    def _in_transit_parcels(self) -> list[Parcel]:
        """Return list of parcels currently in transit."""
        return [
            p for p in self.coordinator.data if not p.is_delivered and not p.is_archived
        ]

    @property
    def native_value(self) -> int:
        """Return the count of active parcels in transit."""
        return len(self._in_transit_parcels)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return parcel tracking numbers and detailed metadata."""
        parcels = self._in_transit_parcels
        return {
            "tracking_numbers": [p.tracking_number for p in parcels],
            "parcels": [self._parcel_detail_dict(p) for p in parcels],
        }


class DHLParcelDeliveredSensor(DHLBaseSensor):
    """Sensor tracking the count of successfully delivered parcels."""

    _attr_icon = "mdi:package-variant-closed-check"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize delivered parcels sensor."""
        super().__init__(coordinator, entry, "delivered")

    @property
    def _delivered_parcels(self) -> list[Parcel]:
        """Return list of delivered parcels."""
        include_archived = self.entry.options.get(
            CONF_INCLUDE_ARCHIVED,
            self.entry.data.get(CONF_INCLUDE_ARCHIVED, DEFAULT_INCLUDE_ARCHIVED),
        )
        source = (
            self.coordinator.all_parcels if include_archived else self.coordinator.data
        )
        return [p for p in source if p.is_delivered]

    @property
    def native_value(self) -> int:
        """Return the count of delivered parcels."""
        return len(self._delivered_parcels)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return delivered parcel details."""
        parcels = self._delivered_parcels
        return {
            "tracking_numbers": [p.tracking_number for p in parcels],
            "parcels": [self._parcel_detail_dict(p) for p in parcels],
        }


class DHLParcelIncomingSensor(DHLBaseSensor):
    """Sensor tracking incoming parcels destined for the user."""

    _attr_icon = "mdi:package-down"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize incoming parcels sensor."""
        super().__init__(coordinator, entry, "incoming")

    @property
    def _incoming_parcels(self) -> list[Parcel]:
        """Return active incoming parcels."""
        return [
            p
            for p in self.coordinator.data
            if p.direction == ParcelDirection.ANKOMMEND
            and not p.is_delivered
            and not p.is_archived
        ]

    @property
    def native_value(self) -> int:
        """Return the count of active incoming parcels."""
        return len(self._incoming_parcels)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return incoming parcel details."""
        parcels = self._incoming_parcels
        all_incoming = [
            p for p in self.coordinator.data if p.direction == ParcelDirection.ANKOMMEND
        ]
        return {
            "total_incoming": len(all_incoming),
            "tracking_numbers": [p.tracking_number for p in parcels],
            "parcels": [self._parcel_detail_dict(p) for p in parcels],
        }


class DHLParcelOutgoingSensor(DHLBaseSensor):
    """Sensor tracking outgoing parcels sent by the user."""

    _attr_icon = "mdi:package-up"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize outgoing parcels sensor."""
        super().__init__(coordinator, entry, "outgoing")

    @property
    def _outgoing_parcels(self) -> list[Parcel]:
        """Return active outgoing parcels."""
        return [
            p
            for p in self.coordinator.data
            if p.direction == ParcelDirection.ABGEHEND
            and not p.is_delivered
            and not p.is_archived
        ]

    @property
    def native_value(self) -> int:
        """Return the count of active outgoing parcels."""
        return len(self._outgoing_parcels)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return outgoing parcel details."""
        parcels = self._outgoing_parcels
        all_outgoing = [
            p for p in self.coordinator.data if p.direction == ParcelDirection.ABGEHEND
        ]
        return {
            "total_outgoing": len(all_outgoing),
            "tracking_numbers": [p.tracking_number for p in parcels],
            "parcels": [self._parcel_detail_dict(p) for p in parcels],
        }


class DHLParcelArchivedSensor(DHLBaseSensor):
    """Sensor tracking the count of archived parcels."""

    _attr_icon = "mdi:archive-outline"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize archived parcels sensor."""
        super().__init__(coordinator, entry, "archived")

    @property
    def _archived_parcels(self) -> list[Parcel]:
        """Return list of archived parcels."""
        source = self.coordinator.all_parcels or self.coordinator.data or []
        return [
            p
            for p in source
            if p.is_archived or str(p.list_type).upper() == "ARCHIVIERT"
        ]

    @property
    def native_value(self) -> int:
        """Return count of archived parcels."""
        return len(self._archived_parcels)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return archived parcel details."""
        parcels = self._archived_parcels
        return {
            "tracking_numbers": [p.tracking_number for p in parcels],
            "parcels": [self._parcel_detail_dict(p) for p in parcels],
        }


class DHLParcelTotalSensor(DHLBaseSensor):
    """Sensor tracking the total count of monitored parcels."""

    _attr_icon = "mdi:package-variant"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize total parcels sensor."""
        super().__init__(coordinator, entry, "total")

    @property
    def native_value(self) -> int:
        """Return the total count of monitored parcels."""
        include_archived = self.entry.options.get(
            CONF_INCLUDE_ARCHIVED,
            self.entry.data.get(CONF_INCLUDE_ARCHIVED, DEFAULT_INCLUDE_ARCHIVED),
        )
        if include_archived:
            return len(self.coordinator.all_parcels or self.coordinator.data)
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return breakdown counts of all monitored parcels."""
        data = self.coordinator.data
        return {
            "in_transit": len(
                [p for p in data if not p.is_delivered and not p.is_archived]
            ),
            "delivered": len([p for p in data if p.is_delivered]),
            "incoming": len(
                [p for p in data if p.direction == ParcelDirection.ANKOMMEND]
            ),
            "outgoing": len(
                [p for p in data if p.direction == ParcelDirection.ABGEHEND]
            ),
            "all_monitored": len(self.coordinator.all_parcels),
        }


class DHLLastUpdateSensor(DHLBaseSensor):
    """Diagnostic sensor reporting the timestamp of the last successful API poll."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-check-outline"

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize last update sensor."""
        super().__init__(coordinator, entry, "last_update")

    @property
    def native_value(self) -> datetime | None:
        """Return the timestamp of the last successful data poll."""
        return self.coordinator.last_poll_time
