# Troubleshooting

- No port: use a USB data cable, reconnect, close serial monitors.
- Unsupported browser: use desktop Chrome/Edge on Windows/Linux; allow the HTTPS provisioner pop-up.
- Chooser cancelled: retry; nothing changed.
- Pop-up blocked: allow pop-ups for HA, then retry.
- Permission denied/busy: close PlatformIO, Arduino monitor and other tabs.
- Wrong Wi-Fi: reconnect and send corrected settings.
- Code expired/used: return to HA and prepare again.
- Worker unavailable: verify internet and retry without erasing.
- Wrong profile: only ESP32-C3-DevKitM-1 is supported.
- Not visible: keep power connected and wait up to two minutes after discovery.

User-facing UI translates errors; raw stack traces remain developer diagnostics.
