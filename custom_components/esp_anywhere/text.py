"""Text platform for ESP Anywhere."""
from homeassistant.components.text import TextEntity, TextMode
from .const import CONF_TENANT_ID
from .entity import EspAnywhereEntity
from .platform_helpers import setup_dynamic_platform

async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data
    def factory(device, description):
        return EspAnywhereText(runtime, device, description, runtime.config[CONF_TENANT_ID])
    entry.async_on_unload(setup_dynamic_platform(runtime, "text", factory, async_add_entities))

class EspAnywhereText(EspAnywhereEntity, TextEntity):
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 48
    def __init__(self, runtime, device, description, tenant_id):
        super().__init__(runtime, device, description)
        self._tenant_id = tenant_id
    @property
    def native_value(self):
        value = self._device.state.get(self._esp_description.entity_id)
        return value if isinstance(value, str) else None
    async def async_set_value(self, value):
        await self._runtime.async_send_command(self._tenant_id, self._device.device_id, "set_entity", {"entity_id": self._esp_description.entity_id, "value": value})
