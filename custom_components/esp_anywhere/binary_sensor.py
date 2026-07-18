"""Binary sensor platform for ESP Anywhere."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EspAnywhereEntity
from .models import EntityDescription
from .platform_helpers import setup_dynamic_platform
from .runtime import DeviceState

CONNECTIVITY_DESCRIPTION = EntityDescription(
    entity_id="esp_anywhere_connectivity",
    platform="binary_sensor",
    name="Connectivity",
    device_class="connectivity",
    entity_category="diagnostic",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up dynamically discovered ESP Anywhere binary sensors."""
    runtime = entry.runtime_data

    def factory(device: DeviceState, description: EntityDescription):
        if description is CONNECTIVITY_DESCRIPTION:
            return EspAnywhereConnectivitySensor(runtime, device, description)
        return EspAnywhereBinarySensor(runtime, device, description)

    entry.async_on_unload(
        setup_dynamic_platform(
            runtime,
            "binary_sensor",
            factory,
            async_add_entities,
            built_in_descriptions=(CONNECTIVITY_DESCRIPTION,),
        )
    )


class EspAnywhereBinarySensor(EspAnywhereEntity, BinarySensorEntity):
    """Push-based binary sensor exposed by an ESP Anywhere device."""

    def __init__(self, runtime, device, description) -> None:
        """Initialize the binary sensor."""
        super().__init__(runtime, device, description)
        self._attr_device_class = description.device_class

    @property
    def is_on(self) -> bool | None:
        """Return the latest reported binary state."""
        value = self._device.state.get(self._esp_description.entity_id)
        return value if isinstance(value, bool) else None


class EspAnywhereConnectivitySensor(EspAnywhereBinarySensor):
    """Diagnostic connectivity state backed by MQTT presence."""

    @property
    def available(self) -> bool:
        """Remain available while Home Assistant can reach the broker."""
        return self._runtime.mqtt.connected

    @property
    def is_on(self) -> bool:
        """Return the device's retained presence state."""
        return self._device.online
