# ESP Anywhere Personal

Private alpha.

## Installation

In HACS, add `https://github.com/kaziksiwy-stack/esp-anywhere-personal` as a Custom repository of type Integration, install ESP Anywhere Personal, and restart Home Assistant.

ESP Anywhere Personal requires your own publicly reachable MQTT broker with TLS enabled.

In the Personal form provide: broker hostname, port, username, password, tenant ID, and TLS setting.

OTA is optional, experimental, and disabled by default. When enabled it also requires a signing key ID, public signing key, and allowed firmware host.
