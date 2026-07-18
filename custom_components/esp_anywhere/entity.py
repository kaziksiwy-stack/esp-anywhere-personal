"""Base entities for ESP Anywhere."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory

from .const import DOMAIN
from .models import EntityDescription
from .runtime import DeviceState, EspAnywhereRuntime


class EspAnywhereEntity(Entity):
    """Base class for an entity backed by an ESP Anywhere device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        runtime: EspAnywhereRuntime,
        device: DeviceState,
        description: EntityDescription,
    ) -> None:
        """Initialize a remotely described entity."""
        self._runtime = runtime
        self._device = device
        self._esp_description = description
        self._attr_unique_id = f"{device.device_id}_{description.entity_id}"
        self._attr_name = description.name
        self._attr_entity_registry_enabled_default = description.enabled_by_default
        if description.entity_category == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif description.entity_category == "config":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Return whether the physical device is online."""
        return self._device.online

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the physical device for the HA device registry."""
        discovery = self._device.discovery
        assert discovery is not None
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.device_id)},
            name=discovery.name,
            manufacturer=discovery.manufacturer,
            model=discovery.model,
            sw_version=discovery.firmware_version,
            configuration_url=discovery.configuration_url,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to push updates after the entity is registered."""
        self.async_on_remove(self._runtime.register_listener(self._handle_update))

    def _handle_update(self, device: DeviceState, suffix: str) -> None:
        """Push relevant device changes into Home Assistant."""
        if device.device_id == self._device.device_id:
            self.async_write_ha_state()
