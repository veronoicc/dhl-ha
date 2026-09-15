"""Data models for DHL parcel tracking."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ParcelDirection(StrEnum):
    """Direction of shipment."""

    ANKOMMEND = "ANKOMMEND"
    ABGEHEND = "ABGEHEND"


class ParcelListType(StrEnum):
    """Status category in shipment list."""

    AKTUELL = "AKTUELL"
    ARCHIVIERT = "ARCHIVIERT"
    ZUGESTELLT = "ZUGESTELLT"


@dataclass
class ParcelEvent:
    """Individual event in shipment history."""

    status: str
    datum: str | None = None
    ruecksendung: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return asdict(self)


@dataclass
class ParcelProgress:
    """Progress status of the parcel."""

    status: str
    current_step: int
    max_steps: int
    datum_aktueller_status: str | None = None
    events: list[ParcelEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert progress to dictionary."""
        return {
            "status": self.status,
            "current_step": self.current_step,
            "max_steps": self.max_steps,
            "datum_aktueller_status": self.datum_aktueller_status,
            "events": [event.to_dict() for event in self.events],
        }


@dataclass
class ParcelDelivery:
    """Delivery details for the parcel."""

    zugestellt_an_empfaenger: bool = False
    zugestellt_an_wunschort: bool = False
    abholcode_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert delivery details to dictionary."""
        return asdict(self)


@dataclass
class ParcelRecipient:
    """Recipient information."""

    name: str | None = None
    city: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert recipient to dictionary."""
        return asdict(self)


@dataclass
class Parcel:
    """Fully typed parcel representation."""

    id: str
    tracking_number: str
    name: str
    direction: ParcelDirection
    list_type: str
    is_delivered: bool
    recipient: ParcelRecipient | None = None
    progress: ParcelProgress | None = None
    delivery: ParcelDelivery | None = None
    sender_logo: str | None = None
    email: str | None = None
    target_country: str | None = None
    expected_delivery_date: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    @property
    def status_text(self) -> str:
        """Return human-readable status text."""
        if self.progress and self.progress.status:
            return self.progress.status
        if self.is_delivered:
            return "Zugestellt"
        return "In Bearbeitung"

    @property
    def summary_text(self) -> str:
        """Return formatted single-line summary string."""
        return f"{self.name} ({self.tracking_number}): {self.status_text}"

    @property
    def is_archived(self) -> bool:
        """Check if parcel is archived."""
        return self.list_type == ParcelListType.ARCHIVIERT

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> Parcel:
        """Parse raw API dictionary into typed Parcel instance."""
        sendungsinfo: dict[str, Any] = data.get("sendungsinfo") or {}
        sendungsdetails: dict[str, Any] = data.get("sendungsdetails") or {}

        parcel_id = str(
            data.get("id") or sendungsinfo.get("gesuchteSendungsnummer") or ""
        )

        tracking_numbers: dict[str, Any] = sendungsdetails.get("sendungsnummern") or {}
        tracking_number = str(
            sendungsinfo.get("gesuchteSendungsnummer")
            or tracking_numbers.get("sendungsnummer")
            or parcel_id
        )

        name = str(sendungsinfo.get("sendungsname") or tracking_number)

        direction_raw = str(sendungsinfo.get("sendungsrichtung") or "ANKOMMEND").upper()
        if direction_raw == "ABGEHEND":
            direction = ParcelDirection.ABGEHEND
        else:
            direction = ParcelDirection.ANKOMMEND

        list_type = str(sendungsinfo.get("sendungsliste") or "AKTUELL")
        is_delivered = bool(sendungsdetails.get("istZugestellt", False))

        recipient: ParcelRecipient | None = None
        pan_empfaenger = sendungsdetails.get("panEmpfaenger")
        if pan_empfaenger and isinstance(pan_empfaenger, dict):
            recipient = ParcelRecipient(
                name=pan_empfaenger.get("name"),
                city=pan_empfaenger.get("ort"),
            )

        progress: ParcelProgress | None = None
        verlauf = sendungsdetails.get("sendungsverlauf")
        if verlauf and isinstance(verlauf, dict):
            raw_events = verlauf.get("events") or []
            events: list[ParcelEvent] = []
            if isinstance(raw_events, list):
                for e in raw_events:
                    if isinstance(e, dict):
                        events.append(
                            ParcelEvent(
                                datum=e.get("datum"),
                                status=str(e.get("status") or ""),
                                ruecksendung=bool(e.get("ruecksendung", False)),
                            )
                        )

            progress = ParcelProgress(
                status=str(verlauf.get("status") or ""),
                current_step=int(verlauf.get("fortschritt") or 0),
                max_steps=int(verlauf.get("maximalFortschritt") or 5),
                datum_aktueller_status=verlauf.get("datumAktuellerStatus"),
                events=events,
            )

        delivery: ParcelDelivery | None = None
        zustellung = sendungsdetails.get("zustellung")
        if zustellung and isinstance(zustellung, dict):
            delivery = ParcelDelivery(
                zugestellt_an_empfaenger=bool(
                    zustellung.get("zugestelltAnEmpfaenger", False)
                ),
                zugestellt_an_wunschort=bool(
                    zustellung.get("zugestelltAnWunschort", False)
                ),
                abholcode_available=bool(zustellung.get("abholcodeAvailable", False)),
            )

        versender = sendungsdetails.get("versender") or {}
        sender_logo = versender.get("logoName") if isinstance(versender, dict) else None

        email = sendungsdetails.get("email")
        target_country = sendungsdetails.get("zielland")

        # Resolve expected delivery date
        expected_delivery: str | None = None
        for key in (
            "voraussichtlicheZustellung",
            "geplanteZustellung",
            "zustellprognose",
        ):
            val = sendungsdetails.get(key)
            if isinstance(val, str) and val.strip():
                expected_delivery = val.strip()
                break

        if not expected_delivery and zustellung and isinstance(zustellung, dict):
            for key in ("zustellfenster", "vslZustellung"):
                val = zustellung.get(key)
                if isinstance(val, str) and val.strip():
                    expected_delivery = val.strip()
                    break

        if not expected_delivery and progress and progress.datum_aktueller_status:
            expected_delivery = progress.datum_aktueller_status
        return cls(
            id=parcel_id,
            tracking_number=tracking_number,
            name=name,
            direction=direction,
            list_type=list_type,
            is_delivered=is_delivered,
            recipient=recipient,
            progress=progress,
            delivery=delivery,
            sender_logo=sender_logo,
            email=email,
            target_country=target_country,
            expected_delivery_date=expected_delivery,
            raw_data=data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert full Parcel to dictionary representation."""
        return {
            "id": self.id,
            "tracking_number": self.tracking_number,
            "name": self.name,
            "direction": str(self.direction),
            "list_type": self.list_type,
            "is_delivered": self.is_delivered,
            "recipient": self.recipient.to_dict() if self.recipient else None,
            "progress": self.progress.to_dict() if self.progress else None,
            "delivery": self.delivery.to_dict() if self.delivery else None,
            "sender_logo": self.sender_logo,
            "email": self.email,
            "target_country": self.target_country,
            "expected_delivery_date": self.expected_delivery_date,
            "status_text": self.status_text,
            "summary_text": self.summary_text,
            "is_archived": self.is_archived,
        }
