# Changelog

## 0.3.0 — 2026-07-31

- Home Assistant can issue five-minute, device-bound activation codes with its own role token; ADMIN_TOKEN remains backend-only.
- Added rate limiting, a 64-device installation cap, redacted audit events and expanded authorization and isolation tests.
- Added the Home Assistant Add device flow, opaque in-memory provisioning sessions and a declarative hardware-profile catalog.
- Added browser flashing with ESP Web Tools and Web Serial configuration without PlatformIO, Git, terminal or config.h.
- Added generic ESP32-C3 factory firmware with USB provisioning, NVS credential storage, activation-code erasure and confirmed factory reset.
- Preserved legacy v0.2.1 devices and the advanced CLI path.
- Added nontechnical onboarding and dedicated provisioning, self-hosting, troubleshooting and profile documentation.
- Confirmed the complete Chromium/Linux browser flow against staging and a real HAOS installation, including physical Board LED control.
- Added resilient Web Serial port reacquisition and chunked configuration writes after ESP Web Tools flashing.


## 0.2.1 — 2026-07-31

- GPIO 8 active-low LED fix and legacy config compatibility.
- HAOS installer backup fix, HA migration and reconnect tests.
- DEVICE_ID-bound activation codes and security tests.
- Guided provisioning, public documentation and release artifacts.

## 0.2.0

- Initial private-alpha Worker, HA integration and ESP32 client.
