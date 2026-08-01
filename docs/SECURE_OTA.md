# Secure OTA

Secure OTA is implemented on the `feature/v0.3.x-secure-ota` staging branch. It is not enabled by the public v0.3.0 production deployment.

## Trust and artifacts

Release manifests use canonical JSON and Ed25519 signatures. The offline private signing key is never stored in Git, Worker, Home Assistant, firmware or CI logs. Firmware and Home Assistant contain only allowlisted public keys. A signed manifest binds the version, hardware profile, protocol/bootstrap minimums, immutable HTTPS firmware URL, byte size and SHA-256 digest. ESP accepts downloads only from approved HTTPS hosts, rejects mismatched profiles and hashes, and blocks downgrade unless an explicitly signed recovery-channel manifest authorizes it.

Key rotation uses an overlap period: ship firmware trusting both the old and new public key, sign releases with the new key, then remove the retired key only after the installed fleet has migrated. A compromised Worker cannot create an accepted image without a trusted private signing key.

## Partitions and health verification

The 4 MB ESP32-C3 layout preserves NVS and uses `otadata`, `ota_0` and `ota_1`. Each application slot is `0x1f0000` bytes. A candidate remains pending until firmware has read NVS, connected to Wi-Fi and authenticated WSS, and sent discovery and state. ESP Anywhere overrides Arduino's early `verifyRollbackLater()` hook so the framework cannot accept the image before these checks. Failure within 60 seconds invalidates the candidate and the ESP-IDF bootloader returns to the previous slot. Repeated attempts are bounded and NVS is not erased.

## Verified staging behavior

On 2026-08-01, an ESP32-C3-DevKitM-1 updated over the public internet from 0.3.9 to a deliberately unhealthy signed 0.3.10 image. The image could not establish WSS and automatically rolled back to 0.3.9 without USB; Wi-Fi and the device token survived. The same device then updated to signed 0.3.11, completed the full health check and remained on 0.3.11.

Firmware size was 1,240,832 bytes (59.2% of one application slot); static RAM usage was 38,668 bytes (11.8%). Existing v0.3.0 devices continue to operate, but their old single-application partition table requires one final browser/USB flash of the OTA bootstrap before internet OTA is possible.
