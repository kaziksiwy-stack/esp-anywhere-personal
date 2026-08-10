"""Number platform for ESP Anywhere."""
from __future__ import annotations
from homeassistant.components.number import NumberEntity
from .const import CONF_TENANT_ID
from .entity import EspAnywhereEntity
from .platform_helpers import setup_dynamic_platform

async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data
    def factory(device, description):
        return EspAnywhereNumber(runtime, device, description, runtime.config[CONF_TENANT_ID])
    entry.async_on_unload(setup_dynamic_platform(runtime, "number", factory, async_add_entities))

class EspAnywhereNumber(EspAnywhereEntity, NumberEntity):
    def __init__(self, runtime, device, description, tenant_id):
        super().__init__(runtime, device, description)
        self._tenant_id = tenant_id
        self._attr_native_min_value = description.min_value
        self._attr_native_max_value = description.max_value
        self._attr_native_step = description.step
    @property
    def native_value(self):
        value = self._device.state.get(self._esp_description.entity_id)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    async def async_set_native_value(self, value):
        await self._runtime.async_send_command(self._tenant_id, self._device.device_id, "set_entity", {"entity_id": self._esp_description.entity_id, "value": value})
