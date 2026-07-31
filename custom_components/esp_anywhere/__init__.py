"""ESP Anywhere Personal integration."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    CONF_BROKER, CONF_PASSWORD, CONF_PORT, CONF_TENANT_ID, CONF_TLS, CONF_USERNAME,
    CONF_TRANSPORT, TRANSPORT_CLOUDFLARE, CONF_RELAY_URL, CONF_INSTALLATION_ID, CONF_TOKEN
)
from .mqtt_client import EspAnywhereMqttClient, MqttSettings
from .websocket_client import EspAnywhereWebsocketClient, CloudflareSettings
from .runtime import EspAnywhereRuntime

PLATFORMS = ["binary_sensor", "button", "sensor", "switch", "text", "update"]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate pre-0.2.1 entries without changing their credentials."""
    if entry.version > 3:
        return False
    data = dict(entry.data)
    if data.get(CONF_TRANSPORT) == TRANSPORT_CLOUDFLARE:
        installation_id = data.get(CONF_INSTALLATION_ID) or data.get(CONF_TENANT_ID)
        if not installation_id:
            return False
        data[CONF_INSTALLATION_ID] = installation_id
        data[CONF_TENANT_ID] = installation_id
    hass.config_entries.async_update_entry(entry, data=data, version=3)
    return True


def mqtt_settings_from_config(config: dict[str, Any]) -> MqttSettings:
    """Recreate direct MQTT settings from persisted config-entry data."""
    return MqttSettings(
        hostname=config[CONF_BROKER], port=config[CONF_PORT],
        username=config[CONF_USERNAME], password=config[CONF_PASSWORD],
        tenant_id=config[CONF_TENANT_ID], tls=config[CONF_TLS],
    )


def cloudflare_settings_from_config(config: dict[str, Any]) -> CloudflareSettings:
    """Recreate Cloudflare WebSocket settings from persisted config-entry data."""
    return CloudflareSettings(
        relay_url=config[CONF_RELAY_URL],
        installation_id=config[CONF_INSTALLATION_ID],
        token=config[CONF_TOKEN],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an ESP Anywhere Personal connection."""
    from homeassistant.exceptions import ConfigEntryNotReady
    config = dict(entry.data)
    runtime: EspAnywhereRuntime

    async def async_handle_message(topic, message) -> None:
        await runtime.async_handle_message(topic, message)

    transport = config.get(CONF_TRANSPORT)

    if transport == TRANSPORT_CLOUDFLARE:
        client = EspAnywhereWebsocketClient(cloudflare_settings_from_config(config), async_handle_message)
    else:
        client = EspAnywhereMqttClient(mqtt_settings_from_config(config), async_handle_message)

    # Note: the property is still called `mqtt` on the runtime for backward compatibility
    # since it abstracts both transports.
    runtime = EspAnywhereRuntime(mqtt=client, config=config)
    entry.runtime_data = runtime

    try:
        await client.async_start()
    except ConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ESP Anywhere Personal config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.mqtt.async_stop()
    return True
