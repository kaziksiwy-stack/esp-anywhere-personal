import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from custom_components.esp_anywhere.websocket_client import (
    EspAnywhereWebsocketClient, CloudflareSettings
)
from custom_components.esp_anywhere.protocol import Topic, Message, PROTOCOL_VERSION
from custom_components.esp_anywhere.const import (
    CONF_TRANSPORT, TRANSPORT_CLOUDFLARE, TRANSPORT_MQTT, CONF_RELAY_URL, CONF_INSTALLATION_ID, CONF_TOKEN
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

    async def test_ignore_bad_json(self):
        await self.client._async_handle_incoming("{bad_json")
        self.handler_mock.assert_not_called()

    async def test_publish_command(self):
        ws_mock = AsyncMock()
        self.client._active_ws = ws_mock
        self.client._connected = True

        topic_str = "esp-anywhere/v1/test-install/dev3/command"
        payload = json.dumps({"command": "turn_on"}).encode("utf-8")

        await self.client.async_publish(topic_str, payload)

        ws_mock.send_json.assert_called_once()
        sent_data = ws_mock.send_json.call_args[0][0]
        self.assertEqual(sent_data["type"], "command")
        self.assertEqual(sent_data["device_id"], "dev3")
        self.assertEqual(sent_data["command"], "turn_on")

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_reconnect_on_error(self, sleep_mock):
        import aiohttp
        session_mock = MagicMock()
        ws_mock = AsyncMock()

        # Async context manager mock for ws_connect
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = ws_mock
        session_mock.ws_connect.return_value = mock_ctx

        async def mock_msg_generator():
            msg = MagicMock()
            msg.type = aiohttp.WSMsgType.ERROR
            yield msg

        async def mock_msg_generator_second_run():
            self.client._stop_event.set()
            return
            yield

        ws_mock.__aiter__.side_effect = [mock_msg_generator(), mock_msg_generator_second_run()]

        with patch("aiohttp.ClientSession", return_value=session_mock):
            await self.client._run()

        self.assertEqual(session_mock.ws_connect.call_count, 2)

if __name__ == '__main__':
    unittest.main()
