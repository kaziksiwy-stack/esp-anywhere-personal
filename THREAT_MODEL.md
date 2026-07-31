# Private-alpha threat model

Assets: Wi-Fi credentials, admin/HA/device tokens, identities and command integrity. Trust boundaries: USB provisioning, flash/NVS, public Worker, Durable Objects and HA.

Controls: verified TLS, random role/device-bound tokens, single-use expiring codes, installation isolation, bounded inputs/payloads, rate/error limits, ignored secret files and no secret logging.

Residual risks: physical flash access, account/token compromise, denial of service and lack of secure boot. OTA is disabled because signatures and rollback are absent. Never control safety-critical equipment.
