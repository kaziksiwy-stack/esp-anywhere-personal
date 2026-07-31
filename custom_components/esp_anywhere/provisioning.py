"""Browser provisioning sessions and HTTP views."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import re
import secrets
import time
import unicodedata

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_INSTALLATION_ID, CONF_RELAY_URL, CONF_TOKEN, DOMAIN
from .relay_url import device_activation_url

SESSION_TTL = 5 * 60
SESSION_KEY = "provision_sessions"
PROFILE_FILE = Path(__file__).with_name("device_profiles.json")
STATIC_DIR = Path(__file__).with_name("static")


@dataclass(slots=True)
class ProvisionSession:
    session_id: str
    created_at: float
    expires_at: float
    device_name: str
    device_id: str
    profile_id: str
    relay_url: str
    installation_id: str
    activation_code: str
    config_entry_id: str


def load_profiles() -> list[dict]:
    """Load the single declarative supported-profile catalog."""
    document = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    return document["profiles"]


def generate_device_id(name: str) -> str:
    """Create a readable collision-resistant identifier."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")[:40] or "esp-device"
    if len(slug) < 3:
        slug = f"esp-{slug}"
    return f"{slug}-{secrets.token_hex(3)}"


async def async_create_session(hass, entry, name: str, device_id: str, profile_id: str) -> ProvisionSession:
    """Ask the Worker for a device-bound code and keep it server-side."""
    profiles = {item["id"] for item in load_profiles()}
    if profile_id not in profiles or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", device_id):
        raise ValueError("invalid_device")
    data = entry.data
    session = async_get_clientsession(hass)
    async with session.post(
        device_activation_url(data[CONF_RELAY_URL]),
        headers={"Authorization": f"Bearer {data[CONF_TOKEN]}"},
        json={"installation_id": data[CONF_INSTALLATION_ID], "device_id": device_id},
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"worker_{response.status}")
        result = await response.json()
    now = time.time()
    item = ProvisionSession(
        session_id=secrets.token_urlsafe(32), created_at=now,
        expires_at=min(now + SESSION_TTL, result["expiresAt"] / 1000),
        device_name=name, device_id=device_id, profile_id=profile_id,
        relay_url=data[CONF_RELAY_URL], installation_id=data[CONF_INSTALLATION_ID],
        activation_code=result["code"],
        config_entry_id=entry.entry_id,
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(SESSION_KEY, {})[item.session_id] = item
    return item


def _session(request, session_id: str) -> ProvisionSession:
    sessions = request.app["hass"].data.setdefault(DOMAIN, {}).setdefault(SESSION_KEY, {})
    item = sessions.get(session_id)
    if item is None or item.expires_at <= time.time():
        sessions.pop(session_id, None)
        raise web.HTTPGone(text="Provisioning session expired")
    return item


class ProvisionPageView(HomeAssistantView):
    url = "/api/esp_anywhere/provision/{session_id}"
    name = "api:esp_anywhere:provision"
    requires_auth = False

    async def get(self, request, session_id):
        _session(request, session_id)
        html = (STATIC_DIR / "provision.html").read_text(encoding="utf-8")
        relay = urlsplit(_session(request, session_id).relay_url)
        provision_origin = urlunsplit(("https", relay.netloc, "", "", ""))
        page = html.replace("__SESSION_ID__", session_id).replace("__PROVISION_ORIGIN__", provision_origin)
        return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-store"})


class ProvisionConfigView(HomeAssistantView):
    url = "/api/esp_anywhere/provision/{session_id}/config"
    name = "api:esp_anywhere:provision_config"
    requires_auth = False

    async def get(self, request, session_id):
        item = _session(request, session_id)
        if not item.activation_code:
            raise web.HTTPGone(text="Provisioning configuration already collected")
        payload = {
            "device_name": item.device_name, "device_id": item.device_id,
            "profile_id": item.profile_id, "relay_url": item.relay_url,
            "installation_id": item.installation_id, "activation_code": item.activation_code,
            "expires_at": item.expires_at,
        }
        item.activation_code = ""
        return self.json(payload, headers={"Cache-Control": "no-store"})


class ProvisionManifestView(HomeAssistantView):
    url = "/api/esp_anywhere/provision/{session_id}/manifest.json"
    name = "api:esp_anywhere:provision_manifest"
    requires_auth = False

    async def get(self, request, session_id):
        item = _session(request, session_id)
        profile = next(profile for profile in load_profiles() if profile["id"] == item.profile_id)
        return self.json({
            "name": "ESP Anywhere", "version": "0.3.0",
            "builds": [{"chipFamily": "ESP32-C3", "parts": [{
                "path": f"/api/esp_anywhere/provision/{session_id}/firmware.bin", "offset": 0,
            }]}], "new_install_prompt_erase": True,
        }, headers={"Cache-Control": "no-store", "X-ESP-Profile": profile["id"]})


class ProvisionStatusView(HomeAssistantView):
    url = "/api/esp_anywhere/provision/{session_id}/status"
    name = "api:esp_anywhere:provision_status"
    requires_auth = False

    async def get(self, request, session_id):
        item = _session(request, session_id)
        entry = request.app["hass"].config_entries.async_get_entry(item.config_entry_id)
        runtime = getattr(entry, "runtime_data", None) if entry else None
        device = runtime.devices.get(item.device_id) if runtime else None
        return self.json({
            "visible": bool(device and device.discovery),
            "online": bool(device and device.online),
        }, headers={"Cache-Control": "no-store"})


class ProvisionFirmwareView(HomeAssistantView):
    url = "/api/esp_anywhere/provision/{session_id}/firmware.bin"
    name = "api:esp_anywhere:provision_firmware"
    requires_auth = False

    async def get(self, request, session_id):
        _session(request, session_id)
        path = STATIC_DIR / "firmware.factory.bin"
        if not path.exists():
            raise web.HTTPServiceUnavailable(text="Firmware artifact is not installed")
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})


def register_views(hass) -> None:
    """Register browser provisioning endpoints once."""
    marker = hass.data.setdefault(DOMAIN, {})
    if marker.get("provision_views_registered"):
        return
    for view in (ProvisionPageView, ProvisionConfigView, ProvisionManifestView, ProvisionStatusView, ProvisionFirmwareView):
        hass.http.register_view(view)
    marker["provision_views_registered"] = True
