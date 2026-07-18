"""ESP Anywhere Personal integration."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
from .const import CONF_BROKER, CONF_PASSWORD, CONF_PORT, CONF_TENANT_ID, CONF_TLS, CONF_USERNAME
from .mqtt_client import EspAnywhereMqttClient, MqttSettings
from .runtime import EspAnywhereRuntime
PLATFORMS = ["binary_sensor", "button", "sensor", "switch", "text", "update"]

def mqtt_settings_from_config(config: dict[str, Any]) -> MqttSettings:
    """Recreate direct MQTT settings from persisted config-entry data."""
    return MqttSettings(
        hostname=config[CONF_BROKER], port=config[CONF_PORT],
        username=config[CONF_USERNAME], password=config[CONF_PASSWORD],
        tenant_id=config[CONF_TENANT_ID], tls=config[CONF_TLS],
    )

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a direct Personal MQTT connection."""
    from homeassistant.exceptions import ConfigEntryNotReady
    config = dict(entry.data)
    runtime: EspAnywhereRuntime
    async def async_handle_message(topic, message) -> None:
        await runtime.async_handle_message(topic, message)
    mqtt = EspAnywhereMqttClient(mqtt_settings_from_config(config), async_handle_message)
    runtime = EspAnywhereRuntime(mqtt=mqtt, config=config)
    entry.runtime_data = runtime
    try:
        await mqtt.async_start()
    except ConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ESP Anywhere Personal config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stop()
    await entry.runtime_data.mqtt.async_stop()
    return True
