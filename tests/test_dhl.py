"""Comprehensive tests for DHL Web integration."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from custom_components.dhl.api import DHLClient, DHLCredentials, _decode_jwt_payload
from custom_components.dhl.const import (
    CONF_DHLA0,
    CONF_DHLB,
    CONF_DHLR0,
    CONF_EMAIL,
    CONF_INCLUDE_ARCHIVED,
    CONF_PASSWORD,
    CONF_POST_NUMBER,
    CONF_VERFOLGEN_CSRF,
)
from custom_components.dhl.diagnostics import TO_REDACT
from custom_components.dhl.models import (
    Parcel,
    ParcelDirection,
    ParcelListType,
)
from custom_components.dhl.sensor import (
    DHLLastUpdateSensor,
    DHLParcelArchivedSensor,
    DHLParcelDeliveredSensor,
    DHLParcelIncomingSensor,
    DHLParcelInTransitSensor,
    DHLParcelOutgoingSensor,
    DHLParcelTotalSensor,
)
from custom_components.dhl.todo import DHLParcelTodoListEntity

SAMPLE_RAW_PARCEL = {
    "id": "00340000000000000001",
    "hasCompleteDetails": True,
    "sendungsinfo": {
        "gesuchteSendungsnummer": "00340000000000000001",
        "sendungsname": "Example Store GmbH",
        "sendungsrichtung": "ANKOMMEND",
        "sendungsliste": "ARCHIVIERT",
    },
    "sendungsdetails": {
        "sendungsnummern": {"sendungsnummer": "00340000000000000001"},
        "versender": {"logoName": "logo-sample"},
        "panEmpfaenger": {"name": "Max Mustermann", "ort": "10115 Berlin"},
        "sendungsverlauf": {
            "datumAktuellerStatus": "2026-08-14T14:22:37+02:00",
            "status": "Zustellung erfolgreich",
            "fortschritt": 5,
            "maximalFortschritt": 5,
            "farbe": 0,
            "iconId": "5",
            "events": [
                {
                    "datum": "2026-08-12T11:31:57+02:00",
                    "status": "Die Sendung wurde elektronisch angekündigt.",
                    "ruecksendung": False,
                },
                {
                    "datum": "2026-08-14T14:22:37+02:00",
                    "status": "Die Sendung wurde erfolgreich zugestellt.",
                    "ruecksendung": False,
                },
            ],
        },
        "services": {
            "statusbenachrichtigung": {
                "aktuellerStatus": True,
                "geplanteZustellung": False,
                "erfolgteZustellung": False,
            }
        },
        "zustellung": {
            "zugestelltAnEmpfaenger": True,
            "zugestelltAnWunschort": False,
            "abholcodeAvailable": False,
        },
        "zielland": "Deutschland",
        "istZugestellt": True,
        "email": "user@example.com",
    },
}

SAMPLE_IN_TRANSIT_PARCEL = {
    "id": "00340000000000000002",
    "hasCompleteDetails": True,
    "sendungsinfo": {
        "gesuchteSendungsnummer": "00340000000000000002",
        "sendungsname": "Online Merchant EU",
        "sendungsrichtung": "ANKOMMEND",
        "sendungsliste": "AKTUELL",
    },
    "sendungsdetails": {
        "sendungsnummern": {"sendungsnummer": "00340000000000000002"},
        "panEmpfaenger": {"name": "Max Mustermann", "ort": "80331 München"},
        "sendungsverlauf": {
            "datumAktuellerStatus": "2026-09-15T08:30:00+02:00",
            "status": "In Zustellung",
            "fortschritt": 4,
            "maximalFortschritt": 5,
            "events": [
                {
                    "datum": "2026-09-15T08:30:00+02:00",
                    "status": "Die Sendung befindet sich in der Zustellung.",
                    "ruecksendung": False,
                }
            ],
        },
        "zustellung": {
            "zugestelltAnEmpfaenger": False,
            "zugestelltAnWunschort": False,
            "abholcodeAvailable": False,
        },
        "istZugestellt": False,
    },
}

SAMPLE_OUTGOING_PARCEL = {
    "id": "00340000000000000003",
    "hasCompleteDetails": True,
    "sendungsinfo": {
        "gesuchteSendungsnummer": "00340000000000000003",
        "sendungsname": "Return Shipment",
        "sendungsrichtung": "ABGEHEND",
        "sendungsliste": "AKTUELL",
    },
    "sendungsdetails": {
        "sendungsnummern": {"sendungsnummer": "00340000000000000003"},
        "sendungsverlauf": {
            "datumAktuellerStatus": "2026-09-15T10:00:00+02:00",
            "status": "Transport zum Ziel-Paketzentrum",
            "fortschritt": 2,
            "maximalFortschritt": 5,
            "events": [],
        },
        "istZugestellt": False,
    },
}


def test_parcel_parsing():
    """Test parsing a raw DHL API parcel dictionary into typed models."""
    parcel = Parcel.from_api_dict(SAMPLE_RAW_PARCEL)

    assert parcel.id == "00340000000000000001"
    assert parcel.tracking_number == "00340000000000000001"
    assert parcel.name == "Example Store GmbH"
    assert parcel.direction == ParcelDirection.ANKOMMEND
    assert parcel.list_type == ParcelListType.ARCHIVIERT
    assert parcel.is_delivered is True
    assert parcel.is_archived is True

    # Recipient
    assert parcel.recipient is not None
    assert parcel.recipient.name == "Max Mustermann"
    assert parcel.recipient.city == "10115 Berlin"

    # Progress & Events
    assert parcel.progress is not None
    assert parcel.progress.status == "Zustellung erfolgreich"
    assert parcel.progress.current_step == 5
    assert parcel.progress.max_steps == 5
    assert len(parcel.progress.events) == 2
    assert (
        parcel.progress.events[0].status
        == "Die Sendung wurde elektronisch angekündigt."
    )
    assert (
        parcel.progress.events[1].status == "Die Sendung wurde erfolgreich zugestellt."
    )

    # Delivery
    assert parcel.delivery is not None
    assert parcel.delivery.zugestellt_an_empfaenger is True
    assert parcel.delivery.zugestellt_an_wunschort is False
    assert parcel.delivery.abholcode_available is False

    # Formatting helpers
    assert "Example Store GmbH" in parcel.summary_text
    assert "00340000000000000001" in parcel.summary_text
    assert parcel.status_text == "Zustellung erfolgreich"
    assert parcel.expected_delivery_date == "2026-08-14T14:22:37+02:00"

    # Serialization
    as_dict = parcel.to_dict()
    assert as_dict["id"] == "00340000000000000001"
    assert as_dict["direction"] == "ANKOMMEND"
    assert as_dict["is_delivered"] is True
    assert as_dict["recipient"]["name"] == "Max Mustermann"
    assert as_dict["progress"]["current_step"] == 5


def test_in_transit_and_outgoing_parcel_parsing():
    """Test parsing active and outgoing shipments."""
    in_transit = Parcel.from_api_dict(SAMPLE_IN_TRANSIT_PARCEL)
    assert in_transit.id == "00340000000000000002"
    assert in_transit.name == "Online Merchant EU"
    assert in_transit.direction == ParcelDirection.ANKOMMEND
    assert in_transit.list_type == ParcelListType.AKTUELL
    assert in_transit.is_delivered is False
    assert in_transit.is_archived is False
    assert in_transit.progress.current_step == 4
    assert in_transit.progress.max_steps == 5
    assert in_transit.status_text == "In Zustellung"

    outgoing = Parcel.from_api_dict(SAMPLE_OUTGOING_PARCEL)
    assert outgoing.id == "00340000000000000003"
    assert outgoing.name == "Return Shipment"
    assert outgoing.direction == ParcelDirection.ABGEHEND
    assert outgoing.is_delivered is False


def test_jwt_payload_decoding():
    """Test JWT token decoding utility."""
    import base64

    payload_json = json.dumps(
        {
            "sub": "auth0|pid|12345",
            "email": "user@example.com",
            "post_number": "1234567890",
            "display_name": "Max Mustermann",
            "exp": 1789493423,
        }
    )
    b64_payload = (
        base64.urlsafe_b64encode(payload_json.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    fake_jwt = f"eyJhbGciOiJSUzI1NiJ9.{b64_payload}.signature"

    decoded = _decode_jwt_payload(fake_jwt)
    assert decoded.get("email") == "user@example.com"
    assert decoded.get("post_number") == "1234567890"
    assert decoded.get("display_name") == "Max Mustermann"
    assert decoded.get("exp") == 1789493423

    # Test fallback claim names
    payload_alt = json.dumps(
        {
            "preferred_username": "fallback@example.com",
            "postnumber": "9876543210",
        }
    )
    b64_alt = (
        base64.urlsafe_b64encode(payload_alt.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    decoded_alt = _decode_jwt_payload(f"eyJ.{b64_alt}.sig")
    assert decoded_alt.get("email") == "fallback@example.com"
    assert decoded_alt.get("post_number") == "9876543210"


def test_diagnostics_redaction_keys():
    """Verify sensitive authentication keys are in the redaction set."""
    assert CONF_DHLA0 in TO_REDACT
    assert CONF_DHLR0 in TO_REDACT
    assert CONF_DHLB in TO_REDACT
    assert CONF_VERFOLGEN_CSRF in TO_REDACT
    assert CONF_PASSWORD in TO_REDACT
    assert CONF_EMAIL in TO_REDACT
    assert CONF_POST_NUMBER in TO_REDACT


def _create_mock_coordinator(parcels: list[Parcel]):
    coordinator = MagicMock()
    coordinator.data = parcels
    coordinator.all_parcels = parcels
    coordinator.last_poll_time = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    return coordinator


def _create_mock_entry(include_archived: bool = False):
    entry = MagicMock()
    entry.entry_id = "test_entry_id_1"
    entry.unique_id = "1234567890"
    entry.title = "DHL (1234567890)"
    entry.options = {CONF_INCLUDE_ARCHIVED: include_archived}
    return entry


def test_sensor_platforms():
    """Test all sensor platform entities with mixed parcel states."""
    p_delivered = Parcel.from_api_dict(SAMPLE_RAW_PARCEL)
    p_transit = Parcel.from_api_dict(SAMPLE_IN_TRANSIT_PARCEL)
    p_outgoing = Parcel.from_api_dict(SAMPLE_OUTGOING_PARCEL)

    coordinator = _create_mock_coordinator([p_delivered, p_transit, p_outgoing])
    entry = _create_mock_entry()

    # 1. In Transit Sensor
    in_transit_sensor = DHLParcelInTransitSensor(coordinator, entry)
    assert (
        in_transit_sensor.native_value == 2
    )  # p_transit + p_outgoing (both not delivered)
    attrs = in_transit_sensor.extra_state_attributes
    assert len(attrs["tracking_numbers"]) == 2
    assert len(attrs["parcels"]) == 2

    # 2. Delivered Sensor
    delivered_sensor = DHLParcelDeliveredSensor(coordinator, entry)
    assert delivered_sensor.native_value == 1  # p_delivered
    attrs_del = delivered_sensor.extra_state_attributes
    assert isinstance(attrs_del, dict)
    assert len(attrs_del["tracking_numbers"]) == 1

    # 3. Incoming Sensor (active incoming in transit)
    incoming_sensor = DHLParcelIncomingSensor(coordinator, entry)
    assert incoming_sensor.native_value == 1  # p_transit (active incoming)
    attrs_inc = incoming_sensor.extra_state_attributes
    assert isinstance(attrs_inc, dict)
    assert attrs_inc["total_incoming"] == 2

    # 4. Outgoing Sensor (active outgoing in transit)
    outgoing_sensor = DHLParcelOutgoingSensor(coordinator, entry)
    assert outgoing_sensor.native_value == 1  # p_outgoing (active outgoing)
    attrs_out = outgoing_sensor.extra_state_attributes
    assert isinstance(attrs_out, dict)
    assert attrs_out["total_outgoing"] == 1

    # 5. Archived Sensor
    archived_sensor = DHLParcelArchivedSensor(coordinator, entry)
    assert archived_sensor.native_value == 1  # p_delivered (list_type: ARCHIVIERT)
    attrs_arc = archived_sensor.extra_state_attributes
    assert isinstance(attrs_arc, dict)
    assert len(attrs_arc["tracking_numbers"]) == 1
    assert archived_sensor.device_info is not None
    assert archived_sensor.device_info.name == "DHL (1234567890)"

    # 6. Total Sensor
    total_sensor = DHLParcelTotalSensor(coordinator, entry)
    assert total_sensor.native_value == 3
    attrs_tot = total_sensor.extra_state_attributes
    assert isinstance(attrs_tot, dict)
    assert attrs_tot["in_transit"] == 2
    assert attrs_tot["delivered"] == 1
    assert attrs_tot["incoming"] == 2
    assert attrs_tot["outgoing"] == 1
    assert attrs_tot["all_monitored"] == 3
    last_update_sensor = DHLLastUpdateSensor(coordinator, entry)
    assert last_update_sensor.native_value == datetime(
        2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc
    )
    assert last_update_sensor.device_info is not None


def test_todo_list_platform():
    """Test To-do list platform parcel item mapping."""
    p_delivered = Parcel.from_api_dict(SAMPLE_RAW_PARCEL)
    p_transit = Parcel.from_api_dict(SAMPLE_IN_TRANSIT_PARCEL)

    coordinator = _create_mock_coordinator([p_delivered, p_transit])
    entry = _create_mock_entry(include_archived=True)

    todo_entity = DHLParcelTodoListEntity(coordinator, entry)
    items = todo_entity.todo_items
    assert items is not None
    assert len(items) == 2

    # Verify delivered item
    item_del = next(i for i in items if i.uid == p_delivered.tracking_number)
    assert item_del.status == "completed"
    assert "Example Store GmbH" in item_del.summary
    assert "Status: Zustellung erfolgreich" in item_del.description

    # Verify in-transit item
    item_transit = next(i for i in items if i.uid == p_transit.tracking_number)
    assert item_transit.status == "needs_action"
    assert "Online Merchant EU" in item_transit.summary
    assert "Step 4/5" in item_transit.description


def test_client_get_shipments_mock():
    """Test DHLClient async_get_shipments with mocked HTTP session."""
    session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"sendungen": [SAMPLE_RAW_PARCEL, SAMPLE_IN_TRANSIT_PARCEL]}
    )

    session.get.return_value.__aenter__.return_value = mock_resp

    creds = DHLCredentials(
        email="user@example.com",
        post_number="1234567890",
        display_name="Max Mustermann",
        dhla0="jwt",
        dhlr0="r0",
        dhlb="b",
        verfolgen_csrf="csrf_token",
        expires_at=9999999999.0,
    )

    client = DHLClient(session, credentials=creds)

    async def run():
        return await client.async_get_shipments()

    parcels = asyncio.run(run())

    assert len(parcels) == 2
    assert parcels[0].id == "00340000000000000001"
    assert parcels[1].id == "00340000000000000002"
