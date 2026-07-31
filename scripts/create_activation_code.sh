#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s <relay_url> <admin_token> <installation_id> <ha|device> [device_id]\n' "$0" >&2
}

if [[ $# -lt 4 || $# -gt 5 ]]; then
    usage
    exit 2
fi

relay_url="${1%/}"
admin_token="$2"
installation_id="$3"
requested_role="$4"
device_id="${5:-}"

case "$requested_role" in
    ha)
        worker_role="home_assistant"
        if [[ -n "$device_id" ]]; then
            printf 'Error: device_id is only valid for the device role.\n' >&2
            exit 2
        fi
        ;;
    device)
        worker_role="device"
        if [[ -z "$device_id" ]]; then
            printf 'Error: device role requires device_id.\n' >&2
            exit 2
        fi
        ;;
    *)
        usage
        exit 2
        ;;
esac

if [[ ! "$installation_id" =~ ^[a-z0-9][a-z0-9_-]{2,63}$ ]]; then
    printf 'Error: invalid installation_id.\n' >&2
    exit 2
fi
if [[ -n "$device_id" && ! "$device_id" =~ ^[a-z0-9][a-z0-9_-]{2,63}$ ]]; then
    printf 'Error: invalid device_id.\n' >&2
    exit 2
fi

if [[ ! "$relay_url" =~ ^https?://[^/]+$ ]]; then
    printf 'Error: relay_url must be an HTTP(S) base URL without /ws.\n' >&2
    exit 2
fi

json_body=$(printf '{"installation_id":"%s","role":"%s","device_id":"%s"}' \
    "$installation_id" "$worker_role" "$device_id")

set +e
response=$(printf '%s' "$json_body" | curl --silent --show-error \
    --connect-timeout 5 --max-time 10 \
    --header "Authorization: Bearer ${admin_token}" \
    --header "Content-Type: application/json" \
    --data-binary @- \
    --write-out $'\n%{http_code}' \
    "${relay_url}/admin/activation-code")
curl_status=$?
set -e

if [[ $curl_status -eq 28 ]]; then
    printf 'Error: Worker request timed out.\n' >&2
    exit 1
elif [[ $curl_status -ne 0 ]]; then
    printf 'Error: Worker request failed (curl exit %d).\n' "$curl_status" >&2
    exit 1
fi

http_status="${response##*$'\n'}"
response_body="${response%$'\n'*}"
case "$http_status" in
    200) ;;
    401|403)
        printf 'Error: Worker rejected ADMIN_TOKEN (HTTP %s).\n' "$http_status" >&2
        exit 1
        ;;
    409)
        printf 'Error: activation code conflict (HTTP 409).\n' >&2
        exit 1
        ;;
    *)
        printf 'Error: Worker returned HTTP %s.\n' "$http_status" >&2
        exit 1
        ;;
esac

printf '%s' "$response_body" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
    code = data["code"]
    expires_at = data["expiresAt"]
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    print("Error: invalid response from Worker.", file=sys.stderr)
    raise SystemExit(1)

print(f"activation_code={code}")
print(f"expires_at={expires_at}")
'
printf 'installation_id=%s\nrole=%s\n' "$installation_id" "$requested_role"
if [[ -n "$device_id" ]]; then
    printf 'device_id=%s\n' "$device_id"
fi
