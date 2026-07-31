import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import sys

# Patch imports to bypass homeassistant version conflicts during tests
sys.modules['aiohttp'] = MagicMock()
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
class ConfigFlowMock:
    async def async_show_form(self, *args, **kwargs):
        return {"type": "form", "step_id": kwargs.get("step_id")}
    async def async_set_unique_id(self, *args, **kwargs):
        pass
    def _abort_if_unique_id_configured(self):
        pass
    async def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}
sys.modules['homeassistant.config_entries'].ConfigFlow = ConfigFlowMock
sys.modules['homeassistant.data_entry_flow'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.selector'] = MagicMock()
sys.modules['homeassistant.helpers.aiohttp_client'] = MagicMock()

from custom_components.esp_anywhere.websocket_client import (
    EspAnywhereWebsocketClient, CloudflareSettings
)
from custom_components.esp_anywhere.relay_url import claim_url, websocket_url

class TestWebsocketClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = CloudflareSettings("ws://localhost:8787", "test-install", "secret-token")
        self.handler_mock = AsyncMock()
        self.client = EspAnywhereWebsocketClient(self.settings, self.handler_mock)

    async def test_mapping_discovery(self):
        payload = json.dumps({
            "type": "discovery",
            "device_id": "dev1",
            "payload": {"name": "Test"}
        })
        await self.client._async_handle_incoming(payload)
        self.handler_mock.assert_called_once()
        topic, message = self.handler_mock.call_args[0]
        self.assertEqual(topic.suffix, "discovery")
        self.assertEqual(topic.device_id, "dev1")
        self.assertEqual(message.payload, {"name": "Test"})

    async def test_mapping_state(self):
        payload = json.dumps({
            "type": "state",
            "device_id": "dev2",
            "payload": {"power": True}
        })
        await self.client._async_handle_incoming(payload)
        self.handler_mock.assert_called_once()
        topic, message = self.handler_mock.call_args[0]
        self.assertEqual(topic.suffix, "state")
        self.assertEqual(topic.device_id, "dev2")
        self.assertEqual(message.payload, {"power": True})

    async def test_mapping_presence(self):
        await self.client._async_handle_incoming(json.dumps({
            "type": "presence", "device_id": "dev1",
            "payload": {"online": True},
        }))
        topic, message = self.handler_mock.call_args[0]
        self.assertEqual(topic.suffix, "presence")
        self.assertIs(message.raw["online"], True)

    async def test_mapping_ota_progress(self):
        await self.client._async_handle_incoming(json.dumps({
            "type": "ota/progress", "device_id": "dev1",
            "state": "downloading", "progress": 25, "command_id": "cmd-1",
        }))
        topic, message = self.handler_mock.call_args[0]
        self.assertEqual(topic.suffix, "ota/progress")
        self.assertEqual(message.raw["progress"], 25)


class TestRelayUrls(unittest.TestCase):
    def test_http_base_urls(self):
        self.assertEqual(claim_url("http://host:8787"), "http://host:8787/claim")
        self.assertEqual(websocket_url("http://host:8787", "home-1"),
                         "ws://host:8787/ws?role=home_assistant&installation_id=home-1")

    def test_https_base_urls(self):
        self.assertEqual(claim_url("https://relay.example"), "https://relay.example/claim")
        self.assertEqual(websocket_url("https://relay.example", "home-1"),
                         "wss://relay.example/ws?role=home_assistant&installation_id=home-1")

    def test_manual_ws_path_is_rejected(self):
        with self.assertRaises(ValueError):
            websocket_url("https://relay.example/ws", "home-1")


class TestConfigMigration(unittest.IsolatedAsyncioTestCase):
    async def test_cloudflare_entry_migration_preserves_token(self):
        from custom_components.esp_anywhere import async_migrate_entry
        entry = MagicMock()
        entry.version = 2
        entry.data = {"transport": "cloudflare_websocket", "relay_url": "https://relay.example", "tenant_id": "home-one", "token": "redacted-test-token"}
        hass = MagicMock()
        self.assertTrue(await async_migrate_entry(hass, entry))
        updated = hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(updated["data"]["installation_id"], "home-one")
        self.assertEqual(updated["data"]["token"], "redacted-test-token")
        self.assertEqual(updated["version"], 3)

if __name__ == "__main__":
    unittest.main()
