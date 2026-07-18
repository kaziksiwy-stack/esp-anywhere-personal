"""Switch platform for ESP Anywhere."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TENANT_ID
from .entity import EspAnywhereEntity
from .models import EntityDescription
from .platform_helpers import setup_dynamic_platform
from .runtime import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up writable switches announced by discovery."""
    runtime = entry.runtime_data

    def factory(device: DeviceState, description: EntityDescription):
        return EspAnywhereSwitch(
            runtime, device, description, runtime.config[CONF_TENANT_ID]
        )

    entry.async_on_unload(
        setup_dynamic_platform(runtime, "switch", factory, async_add_entities)
    )


class EspAnywhereSwitch(EspAnywhereEntity, SwitchEntity):
    """A switch whose state changes require a device acknowledgement."""

    def __init__(self, runtime, device, description, tenant_id: str) -> None:
        """Initialize the switch."""
        super().__init__(runtime, device, description)
        self._tenant_id = tenant_id

    @property
    def is_on(self) -> bool | None:
        """Return the latest state reported by the device."""
        value = self._device.state.get(self._esp_description.entity_id)
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs) -> None:
        """Request an on state and await the terminal acknowledgement."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Request an off state and await the terminal acknowledgement."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        """Send a set_entity command."""
        await self._runtime.async_send_command(
            self._tenant_id,
            self._device.device_id,
            "set_entity",
            {"entity_id": self._esp_description.entity_id, "value": value},
        )
