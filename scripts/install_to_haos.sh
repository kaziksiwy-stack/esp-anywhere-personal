#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s <root@IP_HA:/config|local_config_path> [ssh_port]\n' "$0" >&2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage
    exit 2
fi

destination="$1"
ssh_port="${2:-22}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${repo_root}/custom_components/esp_anywhere"
timestamp="$(date +%Y%m%d-%H%M%S)"
required_files=(websocket_client.py relay_url.py config_flow.py manifest.json)

if [[ ! "$ssh_port" =~ ^[0-9]+$ ]] || ((ssh_port < 1 || ssh_port > 65535)); then
    printf 'Error: invalid SSH port: %s\n' "$ssh_port" >&2
    exit 2
fi

for file in "${required_files[@]}"; do
    [[ -f "${source_dir}/${file}" ]] || {
        printf 'Error: source integration is missing %s.\n' "$file" >&2
        exit 1
    }
done

if [[ "$destination" == *:* ]]; then
    remote_host="${destination%%:*}"
    config_path="${destination#*:}"
    integration_path="${config_path%/}/custom_components/esp_anywhere"
    backup_path="${config_path%/}/custom_components/esp_anywhere_backup_${timestamp}"
    ssh_args=(-p "$ssh_port")
    scp_args=(-P "$ssh_port")

    ssh "${ssh_args[@]}" "$remote_host" \
        "mkdir -p '${config_path%/}/custom_components' && \
         if [ -d '$integration_path' ]; then cp -a '$integration_path' '$backup_path'; fi && \
         mkdir -p '$integration_path'"
    scp "${scp_args[@]}" -r "${source_dir}/." "${remote_host}:${integration_path}/"

    for file in "${required_files[@]}"; do
        ssh "${ssh_args[@]}" "$remote_host" "test -f '${integration_path}/${file}'" || {
            printf 'Error: remote verification failed for %s.\n' "$file" >&2
            exit 1
        }
    done
    printf 'Installed integration at %s:%s\n' "$remote_host" "$integration_path"
    printf 'Backup (when previous integration existed): %s:%s\n' "$remote_host" "$backup_path"
else
    config_path="${destination%/}"
    integration_path="${config_path}/custom_components/esp_anywhere"
    backup_path="${config_path}/custom_components/esp_anywhere_backup_${timestamp}"
    mkdir -p "${config_path}/custom_components"
    [[ ! -d "$integration_path" ]] || cp -a "$integration_path" "$backup_path"
    mkdir -p "$integration_path"
    cp -a "${source_dir}/." "${integration_path}/"
    for file in "${required_files[@]}"; do
        [[ -f "${integration_path}/${file}" ]] || {
            printf 'Error: local verification failed for %s.\n' "$file" >&2
            exit 1
        }
    done
    printf 'Installed integration at %s\n' "$integration_path"
    printf 'Backup (when previous integration existed): %s\n' "$backup_path"
fi

printf 'Home Assistant was not restarted. Restart it manually after reviewing the copy.\n'
