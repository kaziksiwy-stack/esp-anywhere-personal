#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 4 ]]; then
  printf 'Usage: %s <relay_url> <ha_token> <installation_id> <device_id>\n' "$0" >&2; exit 2
fi
relay_url="${1%/}"; ha_token="$2"; installation_id="$3"; device_id="$4"
[[ "$installation_id" =~ ^[a-z0-9][a-z0-9_-]{2,63}$ ]] || { echo 'Invalid installation_id.' >&2; exit 2; }
[[ "$device_id" =~ ^[a-z0-9][a-z0-9_-]{2,63}$ ]] || { echo 'Invalid device_id.' >&2; exit 2; }
body=$(printf '{"installation_id":"%s","device_id":"%s"}' "$installation_id" "$device_id")
response=$(printf '%s' "$body" | curl --silent --show-error --fail-with-body --connect-timeout 5 --max-time 10 \
  --header "Authorization: Bearer ${ha_token}" --header 'Content-Type: application/json' --data-binary @- \
  "${relay_url}/ha/device-activation-code")
printf '%s' "$response" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("activation_code="+d["code"]); print("expires_at="+str(d["expiresAt"]))'
