"""Constants for ESP Anywhere."""

DOMAIN = "esp_anywhere"
PROTOCOL_VERSION = "1.0"
TOPIC_ROOT = "esp-anywhere/v1"

CONF_TRANSPORT = "transport"
TRANSPORT_MQTT = "mqtt"
TRANSPORT_CLOUDFLARE = "cloudflare_websocket"

CONF_RELAY_URL = "relay_url"
CONF_INSTALLATION_ID = "installation_id"
CONF_TOKEN = "token"

CONF_BROKER = "broker"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_TENANT_ID = "tenant_id"
CONF_TLS = "tls"
CONF_SIGNING_KEY_ID = "signing_key_id"
CONF_SIGNING_PUBLIC_KEY = "signing_public_key"
CONF_FIRMWARE_HOST = "firmware_host"
CONF_ENABLE_OTA = "enable_ota"

DEFAULT_PORT = 8883
DEFAULT_TLS = True

# Public trust anchors only. Private signing keys are never part of HA.
OTA_TRUSTED_KEYS = {
    "staging-2026-01": "9klYzANbWthUQZXrfbt6sN3o5snsICJLD4W1IHzon6I=",
}
OTA_MANIFEST_HOST = "esp-anywhere-worker-staging.esp-anywhere-worker.workers.dev"
OTA_FIRMWARE_HOSTS = frozenset({"raw.githubusercontent.com"})
