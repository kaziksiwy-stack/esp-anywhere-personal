import asyncio
import json
import websockets
import argparse

from custom_components.esp_anywhere.websocket_client import EspAnywhereWebsocketClient, CloudflareSettings
from custom_components.esp_anywhere.runtime import EspAnywhereRuntime

class DummyDeviceListener:
    def __init__(self, runtime):
        self.runtime = runtime
        self.device = None

    def on_update(self, device, suffix):
        self.device = device
        print(f"[HA Core Mock] Device {device.device_id} updated. Suffix: {suffix}. State: {device.state}")

async def run_ha_core(ws_url, token, installation_id):
    settings = CloudflareSettings(relay_url=ws_url, installation_id=installation_id, token=token)

    client = None
    runtime = None

    async def async_handle_message(topic, message):
        if runtime:
            await runtime.async_handle_message(topic, message)

    client = EspAnywhereWebsocketClient(settings, async_handle_message)
    runtime = EspAnywhereRuntime(mqtt=client, config={})

    listener = DummyDeviceListener(runtime)
    runtime.register_listener(listener.on_update)

    print("[HA Core Mock] Starting client...")
    await client.async_start()
    print("[HA Core Mock] Client connected.")

    await asyncio.sleep(2)

    if listener.device and listener.device.device_id:
        print("[HA Core Mock] Triggering set_entity command from Switch...")
        try:
            result = await runtime.async_send_command(
                tenant_id=installation_id,
                device_id=listener.device.device_id,
                command="set_entity",
                parameters={"entity_id": "test_switch", "value": True},
                timeout=3.0
            )
            print(f"[HA Core Mock] Command finished with result: {result}")
        except Exception as e:
            print(f"[HA Core Mock] Command failed: {e}")

    await asyncio.sleep(1)
    await client.async_stop()

async def run_device_loop(ws_url, token, installation_id, device_id):
    url = f"{ws_url}?role=device&installation_id={installation_id}&device_id={device_id}&token={token}"
    async with websockets.connect(url) as ws:
        print("[ESP Mock] Connected")

        discovery_msg = {
            "type": "discovery",
            "payload": {
                "name": "Test Node",
                "manufacturer": "Maker",
                "model": "Proto",
                "hardware_profile": "esp32",
                "firmware_version": "1.0.0",
                "entities": [
                    {
                        "id": "test_sensor",
                        "platform": "sensor",
                        "name": "Test Sensor"
                    },
                    {
                        "id": "test_switch",
                        "platform": "switch",
                        "name": "Test Switch",
                        "read_only": False
                    }
                ]
            }
        }
        await ws.send(json.dumps(discovery_msg))
        print("[ESP Mock] Sent discovery")
        await asyncio.sleep(0.5)

        state_sensor = 42
        state_switch = False

        state_msg = {
            "type": "state",
            "payload": {
                "test_sensor": state_sensor,
                "test_switch": state_switch
            }
        }
        await ws.send(json.dumps(state_msg))
        print(f"[ESP Mock] Sent initial state: {state_msg['payload']}")

        async def send_periodic_updates():
            nonlocal state_sensor
            while True:
                await asyncio.sleep(10)
                state_sensor += 1
                update_msg = {
                    "type": "state",
                    "payload": {
                        "test_sensor": state_sensor,
                        "test_switch": state_switch
                    }
                }
                await ws.send(json.dumps(update_msg))
                print(f"[ESP Mock] Sent periodic state update: {update_msg['payload']}")

        async def listen_commands():
            nonlocal state_switch
            async for message in ws:
                data = json.loads(message)
                print(f"[ESP Mock] Received: {data}")

                if data.get("type") == "command" and data.get("command") == "set_entity":
                    command_id = data.get("command_id")
                    params = data.get("parameters", {})

                    if params.get("entity_id") == "test_switch":
                        new_val = params.get("value", False)
                        state_switch = new_val
                        print(f"[ESP Mock] Executed switch. New state: {state_switch}. Sending succeeded...")

                        # Send acknowledgment
                        ack = {
                            "type": "command_result",
                            "command_id": command_id,
                            "state": "succeeded"
                        }
                        await ws.send(json.dumps(ack))

                        # Follow up with state update to reflect the new switch value
                        state_msg = {
                            "type": "state",
                            "payload": {
                                "test_sensor": state_sensor,
                                "test_switch": state_switch
                            }
                        }
                        await ws.send(json.dumps(state_msg))

        # Run both the listener and the periodic updates concurrently
        periodic_task = asyncio.create_task(send_periodic_updates())
        listen_task = asyncio.create_task(listen_commands())

        done, pending = await asyncio.wait(
            [periodic_task, listen_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

async def main():
    parser = argparse.ArgumentParser(description="Test ESP Anywhere WebSocket transport")
    parser.add_argument("--mode", choices=["e2e", "device-only"], default="e2e", help="Run full flow or isolated device")
    parser.add_argument("--ws-url", default="ws://localhost:8787", help="Relay WebSocket URL")
    parser.add_argument("--token", required=True, help="Installation authorization token")
    parser.add_argument("--install-id", default="home-1", help="Installation ID for grouping")
    parser.add_argument("--device-id", default="dev_001", help="Device ID")

    args = parser.parse_args()

    print(f"Starting in mode: {args.mode}")

    if args.mode == "device-only":
        await run_device_loop(args.ws_url, args.token, args.install_id, args.device_id)
    else:
        # e2e mode includes mock HA Client
        task_ha = asyncio.create_task(run_ha_core(args.ws_url, args.token, args.install_id))
        await asyncio.sleep(1)
        task_device = asyncio.create_task(run_device_loop(args.ws_url, args.token, args.install_id, args.device_id))

        await asyncio.gather(task_ha, task_device)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
