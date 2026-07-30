import asyncio
import json
import websockets
import sys

# Prototypowy test e2e
# Zastępuje Cloudflare testami, ale aby to zrobic potrzebny bylby lokalnie dzialajacy serwer mock lub miniflare.
# Zamiast tego przygotuje prosty skrypt, ktory mozna odpalic na dzialajacym websocket (np. cloudflare worker dev).

async def simulate_ha(ws_url, token, installation_id):
    url = f"{ws_url}?role=home_assistant&installation_id={installation_id}&token={token}"
    async with websockets.connect(url) as ws:
        print("[HA] Connected")
        async for message in ws:
            data = json.loads(message)
            print(f"[HA] Received: {data}")
            if data.get("type") == "discovery":
                print("[HA] Sending command to device")
                await ws.send(json.dumps({
                    "type": "command",
                    "device_id": data["device_id"],
                    "command": "turn_on"
                }))

async def simulate_device(ws_url, token, installation_id, device_id):
    url = f"{ws_url}?role=device&installation_id={installation_id}&device_id={device_id}&token={token}"
    async with websockets.connect(url) as ws:
        print("[Device] Connected")
        await ws.send(json.dumps({"type": "ping"}))
        await asyncio.sleep(0.5)
        print("[Device] Sending discovery")
        await ws.send(json.dumps({"type": "discovery", "payload": {"name": "Test Device"}}))
        await asyncio.sleep(0.5)
        print("[Device] Sending state")
        await ws.send(json.dumps({"type": "state", "payload": {"power": True}}))

        async for message in ws:
            data = json.loads(message)
            print(f"[Device] Received: {data}")
            if data.get("type") == "command":
                print("[Device] Sending command_result")
                await ws.send(json.dumps({
                    "type": "command_result",
                    "command_id": "123",
                    "state": "succeeded"
                }))
                break

async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_cloudflare_transport.py <ws_url>")
        sys.exit(1)

    ws_url = sys.argv[1]
    token = "test-token"
    installation_id = "test-install-1"
    device_id = "device-123"

    print(f"Connecting to {ws_url}")
    ha_task = asyncio.create_task(simulate_ha(ws_url, token, installation_id))
    # Dajmy HA chwile na podlaczenie
    await asyncio.sleep(1)
    device_task = asyncio.create_task(simulate_device(ws_url, token, installation_id, device_id))

    await asyncio.gather(ha_task, device_task)

if __name__ == "__main__":
    asyncio.run(main())
