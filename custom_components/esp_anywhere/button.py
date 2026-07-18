"""Button platform for ESP Anywhere."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TENANT_ID
from .entity import EspAnywhereEntity
from .models import EntityDescription
from .platform_helpers import setup_dynamic_platform
from .protocol import ALLOWED_COMMANDS
from .runtime import DeviceState

BUTTON_COMMANDS = ALLOWED_COMMANDS - {"set_entity", "install_update"}

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up command buttons announced by discovery."""
    runtime = entry.runtime_data

    def factory(device: DeviceState, description: EntityDescription):
        return EspAnywhereButton(
            runtime, device, description, runtime.config[CONF_TENANT_ID]
        )

    entry.async_on_unload(
        setup_dynamic_platform(runtime, "button", factory, async_add_entities)
    )


class EspAnywhereButton(EspAnywhereEntity, ButtonEntity):
    """A constrained device command button."""

    def __init__(self, runtime, device, description, tenant_id: str) -> None:
        """Initialize the button and enforce its command allowlist."""
        super().__init__(runtime, device, description)
        if description.command not in BUTTON_COMMANDS:
            raise ValueError("Button discovery contains an unsupported command")
        self._command = description.command
        self._tenant_id = tenant_id

    async def async_press(self) -> None:
        """Publish the configured command and await its result."""
        await self._runtime.async_send_command(
            self._tenant_id,
            self._device.device_id,
            self._command,
            {},
        )

