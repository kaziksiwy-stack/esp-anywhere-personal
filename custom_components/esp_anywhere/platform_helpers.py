"""Helpers for dynamic ESP Anywhere entity platforms."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .models import EntityDescription
from .runtime import DeviceState, EspAnywhereRuntime


def setup_dynamic_platform(
    runtime: EspAnywhereRuntime,
    platform: str,
    factory: Callable[[DeviceState, EntityDescription], object],
    async_add_entities: AddEntitiesCallback,
    built_in_descriptions: tuple[EntityDescription, ...] = (),
) -> Callable[[], None]:
    """Add current and future entities for a platform without duplicates."""
    known: set[str] = set()

    def add_device(device: DeviceState, suffix: str = "discovery") -> None:
        if device.discovery is None or suffix != "discovery":
            return
        new_entities = []
        descriptions = (*built_in_descriptions, *device.discovery.entities)
        for description in descriptions:
            key = f"{device.device_id}:{description.entity_id}"
            if description.platform == platform and key not in known:
                known.add(key)
                new_entities.append(factory(device, description))
        if new_entities:
            async_add_entities(new_entities)

    for device in runtime.devices.values():
        add_device(device)
    return runtime.register_listener(add_device)
