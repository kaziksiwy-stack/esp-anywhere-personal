import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import sys

# Patch imports to bypass homeassistant version conflicts during tests
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

if __name__ == '__main__':
    unittest.main()
