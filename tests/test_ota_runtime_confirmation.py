"""Regression tests for post-reboot OTA confirmation."""

import asyncio
import json
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.modules["homeassistant"] = MagicMock()

from custom_components.esp_anywhere.protocol import Message, Topic
from custom_components.esp_anywhere.runtime import EspAnywhereRuntime


class TestOtaRuntimeConfirmation(unittest.IsolatedAsyncioTestCase):
    async def test_target_discovery_completes_when_success_event_was_lost(self):
        mqtt = MagicMock()
        mqtt.async_publish = AsyncMock()
        runtime = EspAnywhereRuntime(mqtt=mqtt)

        install = asyncio.create_task(
            runtime.async_start_ota(
                "install-one",
                "device-one",
                channel="stable",
                target_version="0.3.6",
                timeout=1,
            )
        )
        await asyncio.sleep(0)

        command_id = next(iter(runtime._pending_ota_targets))
        payload = {
            "name": "Device",
            "manufacturer": "ESP Anywhere",
            "model": "ESP32-C3",
            "hardware_profile": "esp32-c3-devkitm-1",
            "firmware_version": "0.3.6",
            "entities": [],
        }
        await runtime.async_handle_message(
            Topic("install-one", "device-one", "discovery"),
            Message(
                device_id="device-one",
                protocol_version="1.0",
                payload=payload,
                raw={"type": "discovery", "payload": payload},
            ),
        )

        self.assertEqual(await install, {"command_id": command_id, "state": "succeeded"})
        self.assertEqual(runtime.devices["device-one"].ota.state, "confirmed")
        self.assertFalse(runtime._pending_ota_targets)

    async def test_other_version_does_not_complete_pending_update(self):
        mqtt = MagicMock()
        mqtt.async_publish = AsyncMock()
        runtime = EspAnywhereRuntime(mqtt=mqtt)
        task = asyncio.create_task(
            runtime.async_start_ota("install-one", "device-one", channel="stable", target_version="0.3.6", timeout=0.01)
        )
        await asyncio.sleep(0)
        with self.assertRaises(TimeoutError):
            await task


