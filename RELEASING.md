# Release process

1. Align HA, Worker and firmware versions.
2. Update CHANGELOG and run ./scripts/release_gate.sh.
3. Build firmware.bin and SHA256SUMS; commit, tag and push.
4. Publish both artifacts; never attach config.h.
5. Test HACS/manual installation in isolation.

Production requires ESP_ANYWHERE_INSTALLATION Durable Object migration v1 and ADMIN_TOKEN as a Wrangler secret.
