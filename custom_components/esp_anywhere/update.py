"""Firmware update platform for ESP Anywhere."""

from __future__ import annotations

from datetime import timedelta
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_FIRMWARE_HOST,
    CONF_SIGNING_KEY_ID,
    CONF_SIGNING_PUBLIC_KEY,
    CONF_TENANT_ID,
)
from .entity import EspAnywhereEntity
from .manifest import (
    FirmwareManifest,
    parse_and_verify_manifest,
    validate_manifest_url,
    version_is_newer,
)
from .models import EntityDescription
from .runtime import DeviceState

SCAN_INTERVAL = timedelta(seconds=30)

UPDATE_DESCRIPTION = EntityDescription(
    entity_id="esp_anywhere_firmware_update",
    platform="update",
    name="Firmware",
    entity_category="config",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up firmware update entities for capable devices."""
    runtime = entry.runtime_data
    if not all(runtime.config.get(key) for key in (
        CONF_SIGNING_KEY_ID, CONF_SIGNING_PUBLIC_KEY, CONF_FIRMWARE_HOST
    )):
        return
    known: set[str] = set()

    def add_device(device: DeviceState, suffix: str = "discovery") -> None:
        discovery = device.discovery
        if (
            suffix != "discovery"
            or discovery is None
            or discovery.update_manifest_url is None
            or device.device_id in known
        ):
            return
        known.add(device.device_id)
        async_add_entities(
            [
                EspAnywhereUpdateEntity(
                    runtime,
                    device,
                    runtime.config[CONF_TENANT_ID],
                    runtime.config[CONF_SIGNING_KEY_ID],
                    runtime.config[CONF_SIGNING_PUBLIC_KEY],
                    runtime.config[CONF_FIRMWARE_HOST],
                    async_get_clientsession(hass),
                )
            ],
            update_before_add=True,
        )

    for device in runtime.devices.values():
        add_device(device)
    entry.async_on_unload(runtime.register_listener(add_device))


class EspAnywhereUpdateEntity(EspAnywhereEntity, UpdateEntity):
    """Signed pull-based firmware update for one device."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
    )
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = True

    def __init__(
        self, runtime, device, tenant_id, key_id, public_key, firmware_host, session
    ) -> None:
        """Initialize the update entity."""
        super().__init__(runtime, device, UPDATE_DESCRIPTION)
        self._tenant_id = tenant_id
        self._key_id = key_id
        self._public_key = public_key
        self._firmware_host = firmware_host
        self._session = session
        self._manifest: FirmwareManifest | None = None

    @property
    def installed_version(self) -> str | None:
        """Return the device's current firmware version."""
        discovery = self._device.discovery
        return discovery.firmware_version if discovery else None

    @property
    def latest_version(self) -> str | None:
        """Return the latest verified version."""
        return self._manifest.version if self._manifest else self.installed_version

    @property
    def in_progress(self) -> bool | int:
        """Return OTA activity or the reported download percentage."""
        ota = self._device.ota
        if ota is None or ota.state in {"confirmed", "failed", "rollback"}:
            return False
        if ota.state == "downloading":
            return round(ota.progress)
        return True

    @property
    def extra_state_attributes(self) -> dict[str, str | float] | None:
        """Expose the authenticated device OTA lifecycle for diagnostics."""
        ota = self._device.ota
        if ota is None:
            return None
        attributes: dict[str, str | float] = {
            "ota_state": ota.state,
            "ota_progress": ota.progress,
        }
        if ota.error_code is not None:
            attributes["ota_error"] = ota.error_code
        return attributes

    @property
    def release_summary(self) -> str | None:
        """Return the signed short release summary."""
        return self._manifest.summary if self._manifest else None

    @property
    def release_url(self) -> str | None:
        """Return the signed release page URL."""
        return self._manifest.release_url if self._manifest else None

    async def async_update(self) -> None:
        """Fetch and authenticate the current channel manifest."""
        discovery = self._device.discovery
        if discovery is None or discovery.update_manifest_url is None:
            return
        validate_manifest_url(discovery.update_manifest_url, self._firmware_host)
        async with self._session.get(
            self._cache_busted_url(discovery.update_manifest_url),
            timeout=15,
            allow_redirects=False,
            headers={"Cache-Control": "no-cache"},
        ) as response:
            response.raise_for_status()
            document = await response.read()
        self._manifest = parse_and_verify_manifest(
            document,
            trusted_key_id=self._key_id,
            trusted_public_key=self._public_key,
            expected_hardware_profile=discovery.hardware_profile,
        )

    @staticmethod
    def _cache_busted_url(url: str) -> str:
        """Avoid stale branch-tip manifests while preserving the allowlisted host."""
        parsed = urlsplit(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["esp_anywhere_ts"] = str(int(time.time()))
        return urlunsplit(parsed._replace(query=urlencode(query)))

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Compare strict semantic versions."""
        return version_is_newer(latest_version, installed_version)

    async def async_install(
        self, version: str | None, backup: bool, **kwargs
    ) -> None:
        """Ask the device to pull and verify the selected firmware."""
        if backup:
            raise ValueError("Firmware backup is not supported")
        manifest = self._manifest
        discovery = self._device.discovery
        if manifest is None or discovery is None:
            raise RuntimeError("No verified firmware manifest is available")
        if version is not None and version != manifest.version:
            raise ValueError("Installing an arbitrary version is not supported")
        await self._runtime.async_send_command(
            self._tenant_id,
            self._device.device_id,
            "install_update",
            {
                "manifest_url": discovery.update_manifest_url,
                "firmware_url": manifest.firmware_url,
                "size": manifest.firmware_size,
                "version": manifest.version,
                "sha256": manifest.firmware_sha256,
                "key_id": manifest.key_id,
            },
            timeout=300,
        )

    async def async_release_notes(self) -> str | None:
        """Return signed release notes available in the manifest."""
        return self._manifest.summary if self._manifest else None
