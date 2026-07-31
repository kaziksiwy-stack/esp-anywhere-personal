# Web provisioning

Staging page: https://esp-anywhere-worker-staging.esp-anywhere-worker.workers.dev/provision

HA requests a device-bound code using its role token and holds it in memory for at most five minutes. Only an opaque 256-bit session ID appears in the URL. Treat that link as a five-minute bearer secret. The private configuration can be collected only once and is then cleared from HA memory.

ESP Web Tools flashes a generic factory image without secrets. Web Serial sends one JSON packet directly to firmware. Password and code are cleared from JavaScript variables after transmission. Firmware validates data, writes NVS, claims once, deletes the code, and reconnects later with its permanent token.

Supported: current desktop Chrome and Edge on Windows/Linux. HA opens a public Worker HTTPS window and passes the one-time configuration with origin-checked `postMessage`; the configuration is never sent to a Worker endpoint. This keeps Web Serial in a secure context even when local HA itself uses HTTP. Cancelling changes nothing. Reflashing with erase returns provisioning mode. USB factory_reset with confirmation ERASE clears the ESP Anywhere NVS namespace.
