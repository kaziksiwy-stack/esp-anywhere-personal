"""Runtime state for ESP Anywhere."""

from __future__ import annotations

from collections.abc import Callable
import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
import json
from uuid import uuid4

from .models import DeviceDescription, parse_discovery
from .mqtt_client import EspAnywhereMqttClient
from .protocol import Message, ProtocolError, Topic, command_topic, create_command

DeviceListener = Callable[["DeviceState", str], None]
TERMINAL_COMMAND_STATES = frozenset({"succeeded", "failed", "rejected"})
OTA_STATES = frozenset({"fetching_manifest", "downloading", "verifying", "installing", "rebooting", "confirmed", "failed", "rollback"})


@dataclass(frozen=True, slots=True)
class OtaProgress:
    """Latest validated OTA lifecycle report from a device."""

    state: str
    progress: float
    command_id: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BuildStatus:
    """Latest local firmware build state."""
    stage: str = "idle"
    job_id: str | None = None
    version: str | None = None
    error: str | None = None


@dataclass(slots=True)
class DeviceState:
    """Latest validated messages for one physical device."""

    device_id: str
    online: bool = False
    discovery: DeviceDescription | None = None
    state: dict[str, Any] = field(default_factory=dict)
    ota: OtaProgress | None = None


@dataclass(slots=True)
class EspAnywhereRuntime:
    """Objects owned by one Home Assistant config entry."""

    mqtt: EspAnywhereMqttClient
    config: dict[str, Any] = field(default_factory=dict)
    devices: dict[str, DeviceState] = field(default_factory=dict)
    _listeners: set[DeviceListener] = field(default_factory=set)
    _pending_commands: dict[str, asyncio.Future[dict[str, Any]]] = field(
        default_factory=dict
    )
    _pending_ota_targets: dict[str, tuple[str, str]] = field(default_factory=dict)

    def register_listener(self, listener: DeviceListener) -> Callable[[], None]:
        """Register a synchronous device update listener."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def async_stop(self) -> None:
        """Release runtime resources."""

    async def async_send_command(
        self,
        tenant_id: str,
        device_id: str,
        command: str,
        parameters: dict[str, Any],
        *,
        timeout: float = 30,
    ) -> dict[str, Any]:
        """Publish a command and wait for its terminal device result."""
        command_id, payload = create_command(
            device_id, command, parameters, lifetime=timedelta(seconds=timeout)
        )
        future = asyncio.get_running_loop().create_future()
        self._pending_commands[command_id] = future
        try:
            await self.mqtt.async_publish(
                command_topic(tenant_id, device_id), payload, qos=1, retain=False
            )
            result = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            raise TimeoutError(f"Device did not finish command {command_id}") from None
        finally:
            self._pending_commands.pop(command_id, None)

        if result["state"] != "succeeded":
            error = result.get("error", {})
            raise RuntimeError(error.get("message", f"Command {result['state']}"))
        return result

    async def async_start_ota(self, tenant_id: str, device_id: str, *, channel: str, target_version: str, recovery: bool = False, timeout: float = 300) -> dict[str, Any]:
        """Start a constrained OTA flow and wait through post-boot confirmation."""
        if channel not in {"stable", "beta", "recovery"}:
            raise ValueError("Invalid OTA channel")
        if recovery and channel != "recovery":
            raise ValueError("Recovery downgrade requires recovery channel")
        command_id = str(uuid4())
        payload = json.dumps({"type": "ota_start", "command_id": command_id, "channel": channel, "target_version": target_version, "recovery": recovery}, separators=(",", ":")).encode()
        future = asyncio.get_running_loop().create_future()
        self._pending_commands[command_id] = future
        self._pending_ota_targets[command_id] = (device_id, target_version)
        try:
            await self.mqtt.async_publish(command_topic(tenant_id, device_id), payload, qos=1, retain=False)
            result = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_commands.pop(command_id, None)
            self._pending_ota_targets.pop(command_id, None)
        if result["state"] != "succeeded":
            error = result.get("error", {})
            raise RuntimeError(error.get("message", f"OTA {result['state']}"))
        return result

    async def async_handle_message(self, topic: Topic, message: Message) -> None:
        """Apply an incoming message to the in-memory device store."""
        device = self.devices.setdefault(
            topic.device_id, DeviceState(device_id=topic.device_id)
        )
        if topic.suffix == "presence":
            device.online = message.raw.get("online") is True
        elif topic.suffix == "discovery":
            try:
                device.discovery = parse_discovery(message.payload)
            except ProtocolError:
                return
            # ota_success can race the post-reboot WebSocket. Authenticated
            # discovery at the requested version is equivalent confirmation.
            for command_id, (target_device, target_version) in tuple(
                self._pending_ota_targets.items()
            ):
                if (
                    target_device == topic.device_id
                    and device.discovery.firmware_version == target_version
                    and (future := self._pending_commands.get(command_id)) is not None
                    and not future.done()
                ):
                    device.ota = OtaProgress("confirmed", 100.0, command_id)
                    future.set_result({"command_id": command_id, "state": "succeeded"})
        elif topic.suffix == "state":
            device.state = message.payload.copy()
        elif topic.suffix.startswith("state/"):
            entity_id = topic.suffix.removeprefix("state/")
            device.state[entity_id] = message.payload.get("value")
        elif topic.suffix == "command/result":
            command_id = message.raw.get("command_id")
            state = message.raw.get("state")
            if (
                isinstance(command_id, str)
                and state in TERMINAL_COMMAND_STATES
                and (future := self._pending_commands.get(command_id)) is not None
                and not future.done()
            ):
                future.set_result(message.raw)
        elif topic.suffix == "ota/progress":
            state = message.raw.get("state")
            progress = message.raw.get("progress")
            command_id = message.raw.get("command_id")
            error_code = message.raw.get("error_code")
            if (
                state not in OTA_STATES
                or not isinstance(progress, (int, float))
                or isinstance(progress, bool)
                or not 0 <= progress <= 100
                or not isinstance(command_id, str)
                or not 1 <= len(command_id) <= 64
                or (error_code is not None and not isinstance(error_code, str))
            ):
                return
            device.ota = OtaProgress(
                state=state,
                progress=float(progress),
                command_id=command_id,
                error_code=error_code,
            )

        for listener in tuple(self._listeners):
            listener(device, topic.suffix)
