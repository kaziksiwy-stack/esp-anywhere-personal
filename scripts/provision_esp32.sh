#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
client_dir="${repo_root}/esp32_client"
config_file="${client_dir}/include/config.h"
relay_url="${ESP_ANYWHERE_RELAY_URL:-https://esp-anywhere-worker.esp-anywhere-worker.workers.dev}"
installation_id="${ESP_ANYWHERE_INSTALLATION_ID:-}"
dry_run=false
[[ "${1:-}" != "--dry-run" ]] || dry_run=true

valid_id() { [[ "$1" =~ ^[a-z0-9][a-z0-9_-]{2,63}$ ]]; }
prompt() { local label="$1" var="$2"; read -r -p "${label}: " "$var"; }

if $dry_run; then
    wifi_ssid="dry-run-wifi"; wifi_password="dry-run-password"
    device_id="dry-run-device"; installation_id="dry-run-home"
    activation_code="dry-run-home:0123456789abcdef01234567"
    relay_url="https://example.workers.dev"
else
    prompt "Wi-Fi SSID" wifi_ssid
    read -r -s -p "Wi-Fi password: " wifi_password; printf '\n'
    prompt "Installation ID" installation_id
    prompt "Unique DEVICE_ID" device_id
    valid_id "$installation_id" || { printf 'Invalid installation ID.\n' >&2; exit 2; }
    valid_id "$device_id" || { printf 'Invalid DEVICE_ID.\n' >&2; exit 2; }
    prompt "Relay base URL [${relay_url}]" entered_relay
    [[ -z "$entered_relay" ]] || relay_url="${entered_relay%/}"
    read -r -p "Paste activation code, or press Enter to generate it: " activation_code
    if [[ -z "$activation_code" ]]; then
        read -r -s -p "Worker ADMIN_TOKEN: " admin_token; printf '\n'
        response="$(${repo_root}/scripts/create_activation_code.sh "$relay_url" "$admin_token" "$installation_id" device "$device_id")"
        unset admin_token
        activation_code="$(printf '%s\n' "$response" | sed -n 's/^activation_code=//p')"
    fi
fi

valid_id "$installation_id" || { printf 'Invalid installation ID.\n' >&2; exit 2; }
valid_id "$device_id" || { printf 'Invalid DEVICE_ID.\n' >&2; exit 2; }
[[ "$activation_code" =~ ^${installation_id}:[0-9a-f]{24}$ ]] || { printf 'Invalid activation code.\n' >&2; exit 2; }
[[ "$relay_url" =~ ^https://[^/]+$ ]] || { printf 'Production relay must be an HTTPS base URL.\n' >&2; exit 2; }

if $dry_run; then
    printf 'dry-run: validated prompts, identifiers, activation code and HTTPS relay\n'
    printf 'dry-run: would create ignored config.h, build, detect /dev/serial/by-id, upload and monitor\n'
    exit 0
fi

umask 077
escape_c() { printf '%s' "$1" | sed 's/[\\"]/\\&/g'; }
{
    printf '#pragma once\n\n'
    printf '#define WIFI_SSID "%s"\n' "$(escape_c "$wifi_ssid")"
    printf '#define WIFI_PASSWORD "%s"\n' "$(escape_c "$wifi_password")"
    printf '#define RELAY_URL "%s"\n' "$relay_url"
    printf '#define INSTALLATION_ID "%s"\n' "$installation_id"
    printf '#define ACTIVATION_CODE "%s"\n' "$activation_code"
    printf '#define DEVICE_ID "%s"\n' "$device_id"
    printf '#define LED_PIN 8\n#define LED_ACTIVE_LOW true\n'
} > "$config_file"
unset wifi_password activation_code

platformio_bin="${PLATFORMIO_BIN:-platformio}"
(cd "$client_dir" && "$platformio_bin" run)
mapfile -t ports < <(find /dev/serial/by-id -maxdepth 1 -type l -print 2>/dev/null | sort)
(( ${#ports[@]} == 1 )) || { printf 'Expected exactly one serial device; found %d.\n' "${#ports[@]}" >&2; exit 1; }
port="${ports[0]}"
read -r -p "Erase all flash on ${port}? [y/N] " erase
[[ "$erase" != [yY] ]] || (cd "$client_dir" && "$platformio_bin" run --target erase --upload-port "$port")
(cd "$client_dir" && "$platformio_bin" run --target upload --upload-port "$port")
printf 'Upload complete. Monitor does not display Wi-Fi credentials or tokens.\n'
(cd "$client_dir" && "$platformio_bin" device monitor --port "$port" --baud 115200)
