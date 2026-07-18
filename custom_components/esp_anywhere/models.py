"""Validated domain models for ESP Anywhere discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .protocol import ALLOWED_COMMANDS, IDENTIFIER_PATTERN, ProtocolError

SUPPORTED_PLATFORMS = frozenset(
    {"binary_sensor", "button", "light", "number", "select", "sensor", "switch", "text"}
)


@dataclass(frozen=True, slots=True)
class EntityDescription:
    """Validated description of one remotely exposed entity."""

    entity_id: str
    platform: str
    name: str | None
    device_class: str | None = None
    unit_of_measurement: str | None = None
    entity_category: str | None = None
    enabled_by_default: bool = True
    read_only: bool = True
    command: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceDescription:
    """Validated description of one physical device."""

    name: str
    manufacturer: str
    model: str
    hardware_profile: str
    firmware_version: str
    entities: tuple[EntityDescription, ...]
    configuration_url: str | None = None
    update_manifest_url: str | None = None


def parse_discovery(payload: dict[str, Any]) -> DeviceDescription:
    """Parse discovery payload into a safe immutable model."""
    name = _required_string(payload, "name", 64)
    manufacturer = _required_string(payload, "manufacturer", 64)
    model = _required_string(payload, "model", 64)
    hardware_profile = _required_string(payload, "hardware_profile", 64)
    firmware_version = _required_string(payload, "firmware_version", 64)
    if not IDENTIFIER_PATTERN.fullmatch(hardware_profile):
        raise ProtocolError("Invalid hardware_profile")

    raw_entities = payload.get("entities")
    if not isinstance(raw_entities, list) or len(raw_entities) > 128:
        raise ProtocolError("Discovery entities must be a list of at most 128 items")

    entities: list[EntityDescription] = []
    seen_ids: set[str] = set()
    for raw in raw_entities:
        if not isinstance(raw, dict):
            raise ProtocolError("Entity description must be an object")
        entity_id = _required_string(raw, "id", 64)
        if not IDENTIFIER_PATTERN.fullmatch(entity_id):
            raise ProtocolError("Invalid entity id")
        if entity_id in seen_ids:
            raise ProtocolError(f"Duplicate entity id: {entity_id}")
        seen_ids.add(entity_id)

        platform = _required_string(raw, "platform", 32)
        if platform not in SUPPORTED_PLATFORMS:
            raise ProtocolError(f"Unsupported entity platform: {platform}")
        category = _optional_string(raw, "entity_category", 16)
        if category not in (None, "config", "diagnostic"):
            raise ProtocolError("Invalid entity_category")

        read_only = raw.get("read_only", True) is True
        command = _optional_string(raw, "command", 32)
        if platform == "button" and command not in (
            ALLOWED_COMMANDS - {"set_entity", "install_update"}
        ):
            raise ProtocolError("Button requires an allowed command")
        if platform in {"button", "switch", "text"} and read_only:
            raise ProtocolError(f"{platform} must declare read_only=false")
        if platform != "button" and command is not None:
            raise ProtocolError("command is only valid for button entities")

        entities.append(
            EntityDescription(
                entity_id=entity_id,
                platform=platform,
                name=_optional_string(raw, "name", 64),
                device_class=_optional_string(raw, "device_class", 64),
                unit_of_measurement=_optional_string(raw, "unit_of_measurement", 32),
                entity_category=category,
                enabled_by_default=raw.get("enabled_by_default", True) is True,
                read_only=read_only,
                command=command,
            )
        )

    configuration_url = _optional_string(payload, "configuration_url", 512)
    if configuration_url is not None and not configuration_url.startswith("https://"):
        raise ProtocolError("configuration_url must use HTTPS")
    update_manifest_url = _optional_string(payload, "update_manifest_url", 512)
    if update_manifest_url is not None and not update_manifest_url.startswith("https://"):
        raise ProtocolError("update_manifest_url must use HTTPS")

    return DeviceDescription(
        name=name,
        manufacturer=manufacturer,
        model=model,
        hardware_profile=hardware_profile,
        firmware_version=firmware_version,
        entities=tuple(entities),
        configuration_url=configuration_url,
        update_manifest_url=update_manifest_url,
    )


def _required_string(payload: dict[str, Any], key: str, maximum: int) -> str:
    """Return a bounded non-empty string."""
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ProtocolError(f"Invalid or missing {key}")
    return value


def _optional_string(
    payload: dict[str, Any], key: str, maximum: int
) -> str | None:
    """Return a bounded optional string."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise ProtocolError(f"Invalid {key}")
    return value
