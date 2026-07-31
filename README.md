# ESP Anywhere Personal

ESP Anywhere Personal connects Home Assistant to ESP32 devices through either a
Cloudflare Worker WebSocket relay or a private MQTT broker. The Cloudflare path
uses one-time activation codes, device-bound credentials, encrypted WSS traffic,
and a Durable Object per installation.

## Current release

- Home Assistant integration: `0.2.0`
- Worker: `esp-anywhere-worker`
- Production relay: `https://esp-anywhere-worker.esp-anywhere-worker.workers.dev`
- ESP32-C3 firmware: discovery, state, presence, commands, credential persistence,
  and reconnect; OTA commands are explicitly rejected until signed OTA is ready.

## Home Assistant installation

Add `https://github.com/kaziksiwy-stack/esp-anywhere-personal` to HACS as a
custom Integration repository, install **ESP Anywhere Personal**, and restart
Home Assistant.

For the Cloudflare transport, generate a one-time HA activation code:

```bash
read -rsp "ADMIN_TOKEN: " ADMIN_TOKEN; echo
./scripts/create_activation_code.sh \
  https://esp-anywhere-worker.esp-anywhere-worker.workers.dev \
  "$ADMIN_TOKEN" my-home ha
unset ADMIN_TOKEN
```

In the integration form select **Cloudflare WebSocket**, enter the production
relay URL above and the generated activation code. The activation code is
consumed once; Home Assistant stores only the permanent installation token.

The MQTT transport remains available for users with a private TLS MQTT broker.

## ESP32-C3 provisioning

Copy `esp32_client/include/config.example.h` to the ignored `config.h`, fill in
Wi-Fi and relay settings, then generate a device-specific activation code:

```bash
read -rsp "ADMIN_TOKEN: " ADMIN_TOKEN; echo
./scripts/create_activation_code.sh \
  https://esp-anywhere-worker.esp-anywhere-worker.workers.dev \
  "$ADMIN_TOKEN" my-home device esp32_c3_001
unset ADMIN_TOKEN
```

For production WSS, set `RELAY_URL` to the HTTPS relay. The firmware uses
the built-in trusted CA bundle for HTTPS and WSS. Build and upload with PlatformIO:

```bash
cd esp32_client
platformio run
platformio run --target upload --upload-port /dev/ttyUSB0
platformio device monitor --port /dev/ttyUSB0 --baud 115200
```

See [FIRST_REAL_TEST.md](FIRST_REAL_TEST.md) for the detailed LAN test and
rollback procedure. Protocol and security decisions are documented in
[PROTOCOL_CLOUD.md](PROTOCOL_CLOUD.md), [ACTIVATION_FLOW.md](ACTIVATION_FLOW.md),
and [ARCHITECTURE_CLOUD.md](ARCHITECTURE_CLOUD.md).

## Worker development and deployment

```bash
cd worker
npm test
npx tsc --noEmit
npx wrangler dev --ip 0.0.0.0
npx wrangler deploy
```

`ADMIN_TOKEN` must exist as a Wrangler secret in production. Local development
loads it from ignored `worker/.dev.vars`. Never commit activation codes,
permanent tokens, Wi-Fi credentials, `.dev.vars`, or `config.h`.

## Verification

The repository includes Worker unit tests, Home Assistant transport tests, a
PlatformIO build, and a production E2E smoke test covering activation, claim,
discovery, state, presence, command routing, and command acknowledgement.
