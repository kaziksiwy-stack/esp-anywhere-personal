"""Sensor platform for ESP Anywhere."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EspAnywhereEntity
from .models import EntityDescription
from .platform_helpers import setup_dynamic_platform
from .runtime import DeviceState

FIRMWARE_DESCRIPTION = EntityDescription(
    entity_id="esp_anywhere_firmware_version",
    platform="sensor",
    name="Firmware",
    entity_category="diagnostic",
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up dynamically discovered ESP Anywhere sensors."""
    runtime = entry.runtime_data

    def factory(device: DeviceState, description: EntityDescription):
        if description is FIRMWARE_DESCRIPTION:
            return EspAnywhereFirmwareSensor(runtime, device, description)
        return EspAnywhereSensor(runtime, device, description)

    entry.async_on_unload(
        setup_dynamic_platform(
            runtime,
            "sensor",
            factory,
            async_add_entities,
            built_in_descriptions=(FIRMWARE_DESCRIPTION,),
        )
    )


class EspAnywhereSensor(EspAnywhereEntity, SensorEntity):
    """Push-based sensor exposed by an ESP Anywhere device."""

    def __init__(self, runtime, device, description) -> None:
        """Initialize the sensor."""
        super().__init__(runtime, device, description)
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.unit_of_measurement

    @property
    def native_value(self):
        """Return the latest reported state."""
        return self._device.state.get(self._esp_description.entity_id)


class EspAnywhereFirmwareSensor(EspAnywhereSensor):
    """Diagnostic installed firmware version."""

    @property
    def native_value(self) -> str | None:
        """Return the version announced by discovery."""
        discovery = self._device.discovery
        return discovery.firmware_version if discovery is not None else None

