# Private-alpha threat model

Assets: Wi-Fi credentials, admin/HA/device tokens, identities and command integrity. Trust boundaries: USB provisioning, flash/NVS, public Worker, Durable Objects and HA.

Controls: verified TLS, random role/device-bound tokens, single-use expiring codes, installation isolation, bounded inputs/payloads, rate/error limits, ignored secret files and no secret logging. Browser sessions use 256-bit opaque identifiers, no-store responses and one-time configuration retrieval. An origin-checked `postMessage` handoff moves the configuration from local HA to the public HTTPS window; Wi-Fi is supplied locally and never reaches a Worker endpoint.

Residual risks: disclosure or theft of a still-valid opaque provisioning link, a compromised browser or CDN dependency, physical flash access, account/token compromise, denial of service and lack of secure boot. OTA is disabled because signatures and rollback are absent. Never control safety-critical equipment.
