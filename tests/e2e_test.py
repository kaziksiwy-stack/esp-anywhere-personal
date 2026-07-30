import asyncio
import json
import websockets
import argparse
import urllib.request
import urllib.parse
from contextlib import suppress

from custom_components.esp_anywhere.websocket_client import EspAnywhereWebsocketClient, CloudflareSettings
from custom_components.esp_anywhere.runtime import EspAnywhereRuntime

class DummyDeviceListener:
    def __init__(self, runtime):
        self.runtime = runtime
        self.device = None

    def on_update(self, device, suffix):
        self.device = device
        print(f"[HA Core Mock] Device {device.device_id} updated. Suffix: {suffix}. State: {device.state}")

async def claim_activation_code(http_url, code):
    print(f"[Provisioning] Claiming code {code} at {http_url}/claim...")
    data = json.dumps({"code": code}).encode('utf-8')
    req = urllib.request.Request(f"{http_url}/claim", data=data, headers={'Content-Type': 'application/json'})

    # We must run this in a thread or use aiohttp. But urllib is fine for simple script if wrapped.
    def fetch():
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"[Provisioning] Claim failed: {e}")
            return None

    res = await asyncio.to_thread(fetch)
    if res:
        print(f"[Provisioning] Successfully claimed. Received token: {res['token']}")
    return res

async def run_ha_core(ws_url, http_url, admin_token, installation_id):
    # 1. Generate code for HA
    print(f"[Provisioning] Generating HA code for {installation_id}...")
    data = json.dumps({"installation_id": installation_id, "role": "home_assistant"}).encode('utf-8')
    req = urllib.request.Request(f"{http_url}/admin/activation-code", data=data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {admin_token}'})

    def fetch_code():
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))

    code_res = await asyncio.to_thread(fetch_code)
    ha_code = code_res['code']
    print(f"[Provisioning] HA Activation code: {ha_code}")

    # 2. Claim code
    claim_res = await claim_activation_code(http_url, ha_code)
    ha_token = claim_res['token']

    # 3. Connect HA
    settings = CloudflareSettings(relay_url=ws_url, installation_id=installation_id, token=ha_token)

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

    await asyncio.sleep(3)

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

    await asyncio.sleep(2)
    await client.async_stop()

async def run_device_loop(ws_url, http_url, admin_token, installation_id, device_id):
    # 1. Generate code for Device
    print(f"[Provisioning] Generating DEVICE code for {installation_id}...")
    data = json.dumps({"installation_id": installation_id, "role": "device"}).encode('utf-8')
    req = urllib.request.Request(f"{http_url}/admin/activation-code", data=data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {admin_token}'})

    def fetch_code():
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))

    code_res = await asyncio.to_thread(fetch_code)
    dev_code = code_res['code']
    print(f"[Provisioning] Device Activation code: {dev_code}")

    # 2. Claim code
    claim_res = await claim_activation_code(http_url, dev_code)
    dev_token = claim_res['token']

    # 3. Connect Device
    url = f"{ws_url}/ws?role=device&installation_id={installation_id}&device_id={device_id}&token={dev_token}"
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

                        ack = {
                            "type": "command_result",
                            "command_id": command_id,
                            "state": "succeeded"
                        }
                        await ws.send(json.dumps(ack))

                        state_msg = {
                            "type": "state",
                            "payload": {
                                "test_sensor": state_sensor,
                                "test_switch": state_switch
                            }
                        }
                        await ws.send(json.dumps(state_msg))

        periodic_task = asyncio.create_task(send_periodic_updates())
        listen_task = asyncio.create_task(listen_commands())

        done, pending = await asyncio.wait(
            [periodic_task, listen_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

async def main():
    parser = argparse.ArgumentParser(description="Test ESP Anywhere WebSocket transport with Provisioning")
    parser.add_argument("--mode", choices=["e2e", "device-only"], default="e2e", help="Run full flow or isolated device")
    parser.add_argument("--ws-url", default="ws://localhost:8787", help="Relay WebSocket URL")
    parser.add_argument("--http-url", default="http://localhost:8787", help="Relay HTTP URL")
    parser.add_argument("--admin-token", default="testadmin", help="Admin Token for code generation")
    parser.add_argument("--install-id", default="home-1", help="Installation ID for grouping")
    parser.add_argument("--device-id", default="dev_001", help="Device ID")

    args = parser.parse_args()

    print(f"Starting in mode: {args.mode}")

    if args.mode == "device-only":
        await run_device_loop(args.ws_url, args.http_url, args.admin_token, args.install_id, args.device_id)
    else:
        task_ha = asyncio.create_task(run_ha_core(args.ws_url, args.http_url, args.admin_token, args.install_id))
        await asyncio.sleep(2)
        task_device = asyncio.create_task(run_device_loop(args.ws_url, args.http_url, args.admin_token, args.install_id, args.device_id))

        await asyncio.gather(task_ha, task_device)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
