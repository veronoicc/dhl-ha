"""Pytest configuration and Home Assistant stubs for testing without Core installed."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

# If homeassistant is not installed, install lightweight mocks in sys.modules
if "homeassistant" not in sys.modules:
    ha = MagicMock()

    class MockHomeAssistantError(Exception):
        translation_domain: str | None = None
        translation_key: str | None = None

    class MockServiceValidationError(MockHomeAssistantError):
        pass

    ha.exceptions.HomeAssistantError = MockHomeAssistantError
    ha.exceptions.ServiceValidationError = MockServiceValidationError
    ha.exceptions.ConfigEntryAuthFailed = MockHomeAssistantError

    class MockPlatform:
        SENSOR = "sensor"
        TODO = "todo"

    ha.const.Platform = MockPlatform
    ha.const.EntityCategory.CONFIG = "config"
    ha.const.EntityCategory.DIAGNOSTIC = "diagnostic"

    class MockConfigEntry:
        def __init__(self, **kwargs: Any) -> None:
            self.entry_id = kwargs.get("entry_id", "mock_entry_id")
            self.title = kwargs.get("title", "DHL (user@example.com)")
            self.unique_id = kwargs.get("unique_id", "1234567890")
            self.data = kwargs.get("data", {})
            self.options = kwargs.get("options", {})
            self.runtime_data = kwargs.get("runtime_data", None)

        def __class_getitem__(cls, item: Any) -> type[MockConfigEntry]:
            return cls

    ha.config_entries.ConfigEntry = MockConfigEntry

    class MockDataUpdateCoordinator:
        def __init__(
            self, hass: Any, logger: Any, name: str, update_interval: Any = None
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data: Any = None

        def __class_getitem__(cls, item: Any) -> type[MockDataUpdateCoordinator]:
            return cls

    class MockCoordinatorEntity:
        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator

        def __class_getitem__(cls, item: Any) -> type[MockCoordinatorEntity]:
            return cls

    class MockUpdateFailed(Exception):
        pass

    ha.helpers.update_coordinator.DataUpdateCoordinator = MockDataUpdateCoordinator
    ha.helpers.update_coordinator.CoordinatorEntity = MockCoordinatorEntity
    ha.helpers.update_coordinator.UpdateFailed = MockUpdateFailed

    class MockSensorEntity:
        pass

    class MockSensorStateClass:
        TOTAL = "total"
        MEASUREMENT = "measurement"

    class MockSensorDeviceClass:
        TIMESTAMP = "timestamp"

    ha.components.sensor.SensorEntity = MockSensorEntity
    ha.components.sensor.SensorStateClass = MockSensorStateClass
    ha.components.sensor.SensorDeviceClass = MockSensorDeviceClass

    class MockTodoListEntity:
        pass

    class MockTodoItemStatus:
        NEEDS_ACTION = "needs_action"
        COMPLETED = "completed"

    class MockTodoListEntityFeature:
        def __init__(self, val: int = 0) -> None:
            self.val = val

    class MockTodoItem:
        def __init__(
            self,
            uid: str,
            summary: str,
            status: str,
            due: Any = None,
            description: str | None = None,
        ) -> None:
            self.uid = uid
            self.summary = summary
            self.status = status
            self.due = due
            self.description = description

    ha.components.todo.TodoListEntity = MockTodoListEntity
    ha.components.todo.TodoItemStatus = MockTodoItemStatus
    ha.components.todo.TodoListEntityFeature = MockTodoListEntityFeature
    ha.components.todo.TodoItem = MockTodoItem

    def async_redact_data(data: dict[str, Any], to_redact: set[str]) -> dict[str, Any]:
        redacted = dict(data)
        for key in to_redact:
            if key in redacted:
                redacted[key] = "**REDACTED**"
        return redacted

    ha.components.diagnostics.async_redact_data = async_redact_data

    # Device registry stubs
    class MockDeviceEntryType:
        SERVICE = "service"

    class MockDeviceInfo:
        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    ha.helpers.device_registry.DeviceEntryType = MockDeviceEntryType
    ha.helpers.device_registry.DeviceInfo = MockDeviceInfo

    # Register in sys.modules
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = ha.const
    sys.modules["homeassistant.core"] = ha.core
    sys.modules["homeassistant.exceptions"] = ha.exceptions
    sys.modules["homeassistant.config_entries"] = ha.config_entries
    sys.modules["homeassistant.helpers"] = ha.helpers
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha.helpers.aiohttp_client
    sys.modules["homeassistant.helpers.device_registry"] = ha.helpers.device_registry
    sys.modules["homeassistant.helpers.entity_platform"] = ha.helpers.entity_platform
    sys.modules["homeassistant.helpers.update_coordinator"] = (
        ha.helpers.update_coordinator
    )
    sys.modules["homeassistant.helpers.config_validation"] = (
        ha.helpers.config_validation
    )
    sys.modules["homeassistant.util"] = ha.util
    sys.modules["homeassistant.util.dt"] = ha.util.dt
    sys.modules["homeassistant.components"] = ha.components
    sys.modules["homeassistant.components.sensor"] = ha.components.sensor
    sys.modules["homeassistant.components.todo"] = ha.components.todo
    sys.modules["homeassistant.components.diagnostics"] = ha.components.diagnostics
