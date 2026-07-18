"""Asynchronous MQTT transport for ESP Anywhere."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
import logging
import random
import ssl
from typing import Any, Protocol

from .protocol import Message, ProtocolError, Topic, parse_message, parse_topic, topic_filter

_LOGGER = logging.getLogger(__name__)

MessageHandler = Callable[[Topic, Message], Awaitable[None]]
ConnectionHandler = Callable[[bool], None]
ClientFactory = Callable[[], Any]

INITIAL_CONNECT_TIMEOUT = 15
MIN_RECONNECT_DELAY = 1.0
MAX_RECONNECT_DELAY = 60.0


class IncomingMessage(Protocol):
    """Minimum incoming aiomqtt message interface used by the transport."""

    topic: Any
    payload: bytes | bytearray


@dataclass(frozen=True, slots=True)
class MqttSettings:
    """Connection settings for one tenant broker."""

    hostname: str
    port: int
    username: str
    password: str
    tenant_id: str
    tls: bool = True


class EspAnywhereMqttClient:
    """Maintain a resilient MQTT subscription for one tenant."""

    def __init__(
        self,
        settings: MqttSettings,
        message_handler: MessageHandler,
        connection_handler: ConnectionHandler | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        """Initialize the transport without opening a connection."""
        self._settings = settings
        self._message_handler = message_handler
        self._connection_handler = connection_handler
        self._client_factory = client_factory
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._first_connection = asyncio.Event()
        self._connected = False
        self._active_client: Any | None = None

    @property
    def connected(self) -> bool:
        """Return whether the broker session is currently connected."""
        return self._connected

    async def async_start(self) -> None:
        """Start the connection loop and require an initial connection."""
        if self._task is not None:
            raise RuntimeError("MQTT client is already started")
        self._stop_event.clear()
        self._first_connection.clear()
        self._task = asyncio.create_task(self._run(), name="esp_anywhere_mqtt")
        try:
            await asyncio.wait_for(
                self._first_connection.wait(), timeout=INITIAL_CONNECT_TIMEOUT
            )
        except TimeoutError:
            await self.async_stop()
            raise ConnectionError("Timed out connecting to MQTT broker") from None

    async def async_stop(self) -> None:
        """Stop reconnecting and close the active MQTT context."""
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._set_connected(False)

    async def async_publish(
        self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False
    ) -> None:
        """Publish through the active broker session."""
        client = self._active_client
        if client is None or not self._connected:
            raise ConnectionError("MQTT broker is not connected")
        await client.publish(topic, payload=payload, qos=qos, retain=retain)

    async def _run(self) -> None:
        """Connect, consume messages and reconnect with bounded backoff."""
        delay = MIN_RECONNECT_DELAY
        while not self._stop_event.is_set():
            try:
                client_context = (
                    await self._async_create_client()
                    if self._client_factory is None
                    else self._client_factory()
                )
                async with client_context as client:
                    self._active_client = client
                    await client.subscribe(topic_filter(self._settings.tenant_id), qos=1)
                    self._set_connected(True)
                    self._first_connection.set()
                    delay = MIN_RECONNECT_DELAY
                    async for incoming in client.messages:
                        await self._async_handle_incoming(incoming)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # aiomqtt errors are transport-dependent
                _LOGGER.warning("MQTT connection lost: %s", err)
            finally:
                self._active_client = None
                self._set_connected(False)

            if self._stop_event.is_set():
                break
            jittered_delay = delay * random.uniform(0.8, 1.2)
            try:
                await asyncio.wait_for(self._stop_event.wait(), jittered_delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _async_handle_incoming(self, incoming: IncomingMessage) -> None:
        """Validate and dispatch one broker message."""
        try:
            topic = parse_topic(str(incoming.topic))
            if topic.tenant_id != self._settings.tenant_id:
                raise ProtocolError("Message belongs to another tenant")
            message = parse_message(topic, bytes(incoming.payload))
        except ProtocolError as err:
            _LOGGER.warning("Rejected MQTT message on %s: %s", incoming.topic, err)
            return
        await self._message_handler(topic, message)

    async def _async_create_client(self) -> Any:
        """Load blocking dependencies off-loop, then bind client to this loop."""
        aiomqtt, tls_context = await asyncio.to_thread(self._load_client_dependencies)
        return aiomqtt.Client(
            hostname=self._settings.hostname,
            port=self._settings.port,
            username=self._settings.username,
            password=self._settings.password,
            tls_context=tls_context,
            keepalive=60,
            identifier=f"esp-anywhere-ha-{self._settings.tenant_id}",
        )

    def _load_client_dependencies(self):
        """Import metadata and load CA paths in a worker thread."""
        import aiomqtt

        tls_context = ssl.create_default_context() if self._settings.tls else None
        return aiomqtt, tls_context

    def _set_connected(self, connected: bool) -> None:
        """Update connection state and notify only on a transition."""
        if self._connected == connected:
            return
        self._connected = connected
        if self._connection_handler is not None:
            self._connection_handler(connected)
