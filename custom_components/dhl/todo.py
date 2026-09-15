"""Todo platform for DHL parcel tracking deliveries."""

from __future__ import annotations

import logging
from datetime import date, datetime

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import DHLConfigEntry
from .const import CONF_INCLUDE_ARCHIVED, DEFAULT_INCLUDE_ARCHIVED, DOMAIN
from .coordinator import DHLDataUpdateCoordinator
from .models import Parcel, ParcelDirection, ParcelListType

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DHLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DHL to-do list entity from a config entry."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([DHLParcelTodoListEntity(coordinator, entry)])


class DHLParcelTodoListEntity(
    CoordinatorEntity[DHLDataUpdateCoordinator], TodoListEntity
):
    """Interactive deliveries To-do list for a DHL account."""

    _attr_has_entity_name = True
    _attr_translation_key = "parcels"
    _attr_icon = "mdi:truck-delivery-outline"
    _attr_supported_features = TodoListEntityFeature(0)

    def __init__(
        self,
        coordinator: DHLDataUpdateCoordinator,
        entry: DHLConfigEntry,
    ) -> None:
        """Initialize DHL to-do list entity."""
        super().__init__(coordinator)
        self.entry = entry

        unique_base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_base}_parcels"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information linking to the DHL account service."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.unique_id or self.entry.entry_id)},
            name=f"DHL ({self.entry.title})",
            manufacturer="DHL",
            model="Kundenkonto",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _parse_due_date(self, date_str: str | None) -> date | datetime | None:
        """Parse expected delivery date into date or datetime."""
        if not date_str or not isinstance(date_str, str):
            return None
        stripped = date_str.strip()
        parsed_dt = dt_util.parse_datetime(stripped)
        if parsed_dt is not None:
            return parsed_dt
        parsed_d = dt_util.parse_date(stripped)
        if parsed_d is not None:
            return parsed_d
        return None

    def _build_description(self, parcel: Parcel) -> str:
        """Format informative multi-line description for to-do item."""
        direction_label = (
            "Incoming (Ankommend)"
            if parcel.direction == ParcelDirection.ANKOMMEND
            else "Outgoing (Abgehend)"
        )
        lines = [f"Direction: {direction_label}"]

        # Progress & Status
        if parcel.progress:
            step_info = (
                f" (Step {parcel.progress.current_step}/{parcel.progress.max_steps})"
            )
            lines.append(f"Status: {parcel.status_text}{step_info}")
        else:
            lines.append(f"Status: {parcel.status_text}")

        # Expected Delivery
        if parcel.expected_delivery_date:
            lines.append(f"Expected Delivery: {parcel.expected_delivery_date}")

        # Last Event
        if parcel.progress and parcel.progress.events:
            last_event = parcel.progress.events[-1]
            event_line = f"Last Event: {last_event.status}"
            if last_event.datum:
                event_line = f"Last Event ({last_event.datum}): {last_event.status}"
            lines.append(event_line)

        # Recipient
        if parcel.recipient:
            parts = [p for p in (parcel.recipient.name, parcel.recipient.city) if p]
            if parts:
                lines.append(f"Recipient: {', '.join(parts)}")

        # Pickup / Packstation Code
        if parcel.delivery and parcel.delivery.abholcode_available:
            lines.append("Packstation / Pickup Code: Available in DHL App")
        elif parcel.delivery and parcel.delivery.zugestellt_an_wunschort:
            lines.append("Delivery Location: Delivered to designated drop-off place")

        return "\n".join(lines)

    def _parcel_to_todo_item(self, parcel: Parcel) -> TodoItem:
        """Convert a Parcel model into a Home Assistant TodoItem."""
        status = (
            TodoItemStatus.COMPLETED
            if parcel.is_delivered
            else TodoItemStatus.NEEDS_ACTION
        )
        summary = f"{parcel.name} ({parcel.tracking_number})"
        due = self._parse_due_date(parcel.expected_delivery_date)
        description = self._build_description(parcel)

        return TodoItem(
            uid=parcel.tracking_number,
            summary=summary,
            status=status,
            due=due,
            description=description,
        )

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return the current list of delivery items."""
        include_archived = self.entry.options.get(
            CONF_INCLUDE_ARCHIVED, DEFAULT_INCLUDE_ARCHIVED
        )

        source_parcels = (
            self.coordinator.all_parcels if include_archived else self.coordinator.data
        )
        if not include_archived:
            source_parcels = [
                p for p in source_parcels if p.list_type != ParcelListType.ARCHIVIERT
            ]

        return [self._parcel_to_todo_item(p) for p in source_parcels]

    async def async_get_todo_items(self) -> list[TodoItem]:
        """Return list of todo items."""
        return self.todo_items or []
