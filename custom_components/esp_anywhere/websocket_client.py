"""Asynchronous Cloudflare WebSocket transport for ESP Anywhere."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
import json
import logging
import random
import aiohttp

from .protocol import Message, ProtocolError, Topic, PROTOCOL_VERSION

_LOGGER = logging.getLogger(__name__)

MessageHandler = Callable[[Topic, Message], Awaitable[None]]
ConnectionHandler = Callable[[bool], None]

MIN_RECONNECT_DELAY = 1.0
MAX_RECONNECT_DELAY = 60.0


@dataclass(frozen=True, slots=True)
class CloudflareSettings:
    """Connection settings for Cloudflare WebSocket transport."""
    relay_url: str
    installation_id: str
    token: str


class EspAnywhereWebsocketClient:
    """Maintain a resilient WebSocket connection to Cloudflare Worker."""

    def __init__(
        self,
        settings: CloudflareSettings,
        message_handler: MessageHandler,
        connection_handler: ConnectionHandler | None = None,
    ) -> None:
        """Initialize the transport without opening a connection."""
        self._settings = settings
        self._message_handler = message_handler
        self._connection_handler = connection_handler
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._first_connection = asyncio.Event()
        self._connected = False
        self._active_ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def connected(self) -> bool:
        """Return whether the websocket session is currently connected."""
        return self._connected

    async def async_start(self) -> None:
        """Start the connection loop and require an initial connection."""
        if self._task is not None:
            raise RuntimeError("WebSocket client is already started")
        self._stop_event.clear()
        self._first_connection.clear()
        self._task = asyncio.create_task(self._run(), name="esp_anywhere_ws")
        try:
            await asyncio.wait_for(
                self._first_connection.wait(), timeout=15
            )
        except TimeoutError:
            await self.async_stop()
            raise ConnectionError("Timed out connecting to WebSocket relay") from None

    async def async_stop(self) -> None:
        """Stop reconnecting and close the active WebSocket context."""
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        if self._session:
            await self._session.close()
            self._session = None
        self._set_connected(False)

    async def async_publish(
        self, topic_str: str, payload: bytes, *, qos: int = 1, retain: bool = False
    ) -> None:
        """Publish through the active WebSocket session.
        Since we abstract MQTT, we must convert MQTT topic/payload back to WS format.
        Expected topic: esp-anywhere/v1/{tenant_id}/{device_id}/command
        """
        ws = self._active_ws
        if ws is None or not self._connected:
            raise ConnectionError("WebSocket is not connected")

        parts = topic_str.split('/')
        if len(parts) >= 4 and parts[-1] == 'command':
            device_id = parts[3]
            try:
                data = json.loads(payload.decode('utf-8'))
                # Pack back to Worker expected format
                ws_payload = {
                    "type": "command",
                    "device_id": device_id,
                    **data
                }
                await ws.send_json(ws_payload)
            except json.JSONDecodeError:
                pass

    async def _run(self) -> None:
        """Connect, consume messages and reconnect with bounded backoff."""
        delay = MIN_RECONNECT_DELAY
        self._session = aiohttp.ClientSession()

        url = f"{self._settings.relay_url}?role=home_assistant&installation_id={self._settings.installation_id}"
        headers = {"Authorization": f"Bearer {self._settings.token}"}

        while not self._stop_event.is_set():
            try:
                async with self._session.ws_connect(url, headers=headers) as ws:
                    self._active_ws = ws
                    self._set_connected(True)
                    self._first_connection.set()
                    delay = MIN_RECONNECT_DELAY

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._async_handle_incoming(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning("WebSocket connection lost: %s", err)
            finally:
                self._active_ws = None
                self._set_connected(False)

            if self._stop_event.is_set():
                break
            jittered_delay = delay * random.uniform(0.8, 1.2)
            try:
                await asyncio.wait_for(self._stop_event.wait(), jittered_delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _async_handle_incoming(self, data_str: str) -> None:
        """Parse incoming JSON and dispatch to runtime as MQTT-like Message."""
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return

        if not isinstance(data, dict):
            return

        msg_type = data.get("type")
        device_id = data.get("device_id")

        if not device_id or not isinstance(device_id, str):
            return

        # Map WebSocket message to fake MQTT Topic and Message
        # We assume tenant_id = installation_id for the Topic representation
        suffix = ""
        payload_data = {}

        if msg_type == "discovery":
            suffix = "discovery"
            payload_data = data.get("payload", {})
        elif msg_type == "state":
            suffix = "state"
            payload_data = data.get("payload", {})
        elif msg_type == "command_result":
            suffix = "command/result"
            # Command result in runtime expects state in raw, not in payload
            pass
        else:
            return

        topic = Topic(
            tenant_id=self._settings.installation_id,
            device_id=device_id,
            suffix=suffix
        )

        # In runtime.py async_handle_message, it looks at message.payload for state/discovery
        # and message.raw for command/result.
        # We craft a Message that satisfies this.
        message = Message(
            device_id=device_id,
            protocol_version=PROTOCOL_VERSION,
            payload=payload_data,
            raw=data
        )

        await self._message_handler(topic, message)


    def _set_connected(self, connected: bool) -> None:
        """Update connection state and notify only on a transition."""
        if self._connected == connected:
            return
        self._connected = connected
        if self._connection_handler is not None:
            self._connection_handler(connected)
