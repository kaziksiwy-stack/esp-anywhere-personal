# ESP Anywhere Personal

ESP Anywhere connects a supported ESP32-C3 to Home Assistant through an encrypted Cloudflare relay. Normal setup uses HACS and a browser—no terminal, Git, PlatformIO, config.h, ADMIN_TOKEN, installation ID, or manually chosen device ID.

> v0.3.0 is under development on a separate branch. Staging provisioner: https://esp-anywhere-worker-staging.esp-anywhere-worker.workers.dev/provision. Stable v0.2.1 remains unchanged. This private alpha must not control safety-critical equipment.

## Supported hardware

- Espressif ESP32-C3-DevKitM-1
- native USB CDC, 4 MB flash, huge_app.csv
- board LED on GPIO 8, active-low

Only profiles in custom_components/esp_anywhere/device_profiles.json appear in the UI.

## Install with HACS

1. Add this repository to HACS as an Integration.
2. Install ESP Anywhere Personal and restart Home Assistant.
3. Add it from Settings → Devices & services.
4. Enter the public relay and one-time HA activation code supplied by the service administrator.

The administrator code is needed once for HA. End users never receive Worker ADMIN_TOKEN.

## Add your first ESP

HA → Configure ESP Anywhere → Add device → name + board → short-lived browser session → USB flash → Wi-Fi over Web Serial → claim → WSS → automatic discovery in the same HA entry

1. Open the configured integration and choose Configure / Add device.
2. Enter a friendly name and select ESP32-C3-DevKitM-1.
3. Confirm the automatically generated stable ID.
4. Open the short-lived provisioning page shown by HA.
5. In desktop Chrome or Edge on Windows/Linux, connect the ESP with a USB data cable.
6. Select the port, flash generic firmware, enter Wi-Fi and choose Save configuration and connect.
7. Wait for Wi-Fi, claim, Worker, discovery and visible in Home Assistant.
8. Test Connectivity, Uptime, Firmware and Board LED.

Wi-Fi and activation code never enter a URL or public firmware. They exist briefly in browser memory, travel over USB, are stored in NVS, and the code is deleted after claim.

See docs/QUICK_START.md, docs/WEB_PROVISIONING.md, docs/TROUBLESHOOTING.md and docs/DEVICE_PROFILES.md.

## Alpha limitations

- Web Serial requires desktop Chrome/Edge; Safari, Firefox, iOS and Android are unsupported. The integration hands off from HA to the public HTTPS provisioner, so a local HA opened over HTTP remains supported.
- A person must confirm the USB chooser and physical LED.
- OTA remains disabled pending signatures and rollback.
- Limit: 64 devices per installation and 5 prepared codes per minute.
- There is no end-user account or revocation panel yet.

## Security model

Each installation has a Durable Object and separate HA/device credentials. HA creates a five-minute single-use code only for a new device in its own installation. Device tokens cannot create codes. Credentials bind installation and device IDs. Production uses HTTPS/WSS with CA verification. Audit records contain event type, device ID and time—not tokens, codes, Wi-Fi or secret payloads.

See SECURITY.md and THREAT_MODEL.md.

## Advanced: CLI, self-hosting and development

scripts/provision_esp32.sh remains a developer/recovery path. It accepts a code or HA-role token from ESP_ANYWHERE_HA_TOKEN_FILE; it never needs ADMIN_TOKEN. Legacy config.h devices remain compatible with v0.2.1.

Backend administrators set ADMIN_TOKEN only to bootstrap HA. See docs/SELF_HOSTING.md, PROTOCOL_CLOUD.md, ARCHITECTURE_CLOUD.md and RELEASING.md. MQTT remains an advanced transport.

## License

MIT; see LICENSE.
