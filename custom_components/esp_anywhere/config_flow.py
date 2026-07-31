"""Config flow for ESP Anywhere."""
from __future__ import annotations
import base64
import binascii
from typing import Any
from urllib.parse import urlsplit
import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BROKER, CONF_ENABLE_OTA, CONF_FIRMWARE_HOST, CONF_PASSWORD, CONF_PORT,
    CONF_SIGNING_KEY_ID, CONF_SIGNING_PUBLIC_KEY, CONF_TENANT_ID, CONF_TLS,
    CONF_USERNAME, DEFAULT_PORT, DEFAULT_TLS, DOMAIN,
    CONF_TRANSPORT, TRANSPORT_MQTT, TRANSPORT_CLOUDFLARE,
    CONF_RELAY_URL, CONF_INSTALLATION_ID, CONF_TOKEN
)
from .relay_url import claim_url

def _required_text(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 512:
        raise vol.Invalid("required")
    return value

def _required_secret(value: str) -> str:
    if not value or not value.strip() or len(value) > 512:
        raise vol.Invalid("required")
    return value

def _public_key(value: str) -> str:
    value = _required_text(value)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise vol.Invalid("invalid_public_key") from error
    if len(decoded) != 32:
        raise vol.Invalid("invalid_public_key")
    return value

def _firmware_host(value: str) -> str:
    value = _required_text(value).lower()
    parsed = urlsplit(f"//{value}")
    try:
        port = parsed.port
    except ValueError as error:
        raise vol.Invalid("invalid_firmware_host") from error
    if parsed.hostname != value or port is not None or any(c in value for c in ("/", "@", "?", "#")):
        raise vol.Invalid("invalid_firmware_host")
    return value


class EspAnywhereConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure ESP Anywhere."""
    VERSION = 3

    def __init__(self) -> None:
        super().__init__()
        self._personal_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose transport."""
        if user_input is not None:
            if user_input[CONF_TRANSPORT] == TRANSPORT_MQTT:
                return await self.async_step_mqtt()
            else:
                return await self.async_step_cloudflare()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_TRANSPORT, default=TRANSPORT_CLOUDFLARE): vol.In([TRANSPORT_MQTT, TRANSPORT_CLOUDFLARE])
            })
        )

    async def async_step_cloudflare(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Collect Cloudflare WebSocket settings and claim activation code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                relay_url = _required_text(user_input[CONF_RELAY_URL])
                activation_code = _required_secret(user_input.get("activation_code", ""))

                # Perform claim against the worker via HTTP.
                session = async_get_clientsession(self.hass)
                http_url = claim_url(relay_url)

                async with session.post(http_url, json={"code": activation_code}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        token = data["token"]
                        installation_id = data["installation_id"]
                        role = data["role"]

                        if role != "home_assistant":
                            errors["base"] = "invalid_role"
                        else:
                            self._personal_data = {
                                CONF_TRANSPORT: TRANSPORT_CLOUDFLARE,
                                CONF_RELAY_URL: relay_url,
                                CONF_INSTALLATION_ID: installation_id,
                                CONF_TOKEN: token,
                                CONF_TENANT_ID: installation_id, # Fallback compatibility
                            }
                            return await self._finish()
                    elif resp.status == 400:
                        errors["base"] = "invalid_code"
                    else:
                        errors["base"] = "cannot_connect"

            except (vol.Invalid, ValueError):
                errors["base"] = "invalid_input"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="cloudflare",
            data_schema=vol.Schema({
                vol.Required(CONF_RELAY_URL, default="http://localhost:8787"): str,
                vol.Required("activation_code"): str,
            }),
            errors=errors
        )

    async def async_step_mqtt(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Collect direct MQTT settings without requiring OTA."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input[CONF_BROKER] = _required_text(user_input[CONF_BROKER])
                user_input[CONF_USERNAME] = _required_text(user_input[CONF_USERNAME])
                user_input[CONF_PASSWORD] = _required_secret(user_input[CONF_PASSWORD])
                user_input[CONF_TENANT_ID] = _required_text(user_input[CONF_TENANT_ID])
            except vol.Invalid:
                errors["base"] = "invalid_input"
            else:
                enable_ota = user_input.pop(CONF_ENABLE_OTA)
                self._personal_data = dict(user_input)
                self._personal_data[CONF_TRANSPORT] = TRANSPORT_MQTT
                if enable_ota:
                    return await self.async_step_ota()
                return await self._finish()

        return self.async_show_form(step_id="mqtt", data_schema=vol.Schema({
            vol.Required(CONF_BROKER): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_TENANT_ID): str,
            vol.Required(CONF_TLS, default=DEFAULT_TLS): bool,
            vol.Required(CONF_ENABLE_OTA, default=False): bool,
        }), errors=errors)

    async def async_step_ota(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Collect optional public OTA trust data."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input[CONF_SIGNING_KEY_ID] = _required_text(user_input[CONF_SIGNING_KEY_ID])
                user_input[CONF_SIGNING_PUBLIC_KEY] = _public_key(user_input[CONF_SIGNING_PUBLIC_KEY])
                user_input[CONF_FIRMWARE_HOST] = _firmware_host(user_input[CONF_FIRMWARE_HOST])
            except vol.Invalid:
                errors["base"] = "invalid_input"
            else:
                self._personal_data.update(user_input)
                return await self._finish()
        return self.async_show_form(step_id="ota", data_schema=vol.Schema({
            vol.Required(CONF_SIGNING_KEY_ID): str,
            vol.Required(CONF_SIGNING_PUBLIC_KEY): str,
            vol.Required(CONF_FIRMWARE_HOST): str,
        }), errors=errors)

    async def _finish(self) -> FlowResult:
        transport = self._personal_data.get(CONF_TRANSPORT)
        if transport == TRANSPORT_CLOUDFLARE:
            unique_id = f"cloudflare_{self._personal_data[CONF_RELAY_URL]}/{self._personal_data[CONF_INSTALLATION_ID]}"
        else:
            unique_id = f"{self._personal_data[CONF_BROKER]}:{self._personal_data[CONF_PORT]}/{self._personal_data[CONF_TENANT_ID]}"

        await self.async_set_unique_id(unique_id.lower())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="ESP Anywhere Personal", data=self._personal_data)
