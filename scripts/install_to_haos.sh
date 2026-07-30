#!/usr/bin/env bash
set -e

if [ "$#" -ne 1 ]; then
    echo "Użycie: \$0 <ścieżka_do_config_ha_lub_user@host:/config>"
    echo "Przykłady:"
    echo "  \$0 /ścieżka/do/config"
    echo "  \$0 root@192.168.1.100:/mnt/data/supervisor/homeassistant"
    # Avoiding 'exit' directly in the stream context to bypass parser issue
    kill -INT $$
fi

DEST="$1"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/custom_components/esp_anywhere"

echo "Przygotowuję instalację ESP Anywhere Personal..."

if [[ "$DEST" == *":"* ]]; then
    HOST_PART=$(echo "$DEST" | cut -d ':' -f 1)
    PATH_PART=$(echo "$DEST" | cut -d ':' -f 2)
    BACKUP_PATH="${PATH_PART}/custom_components/esp_anywhere_backup_$(date +%s)"

    echo "Cel zdalny ($HOST_PART). Próba wykonania backupu..."
    ssh "$HOST_PART" "if [ -d '${PATH_PART}/custom_components/esp_anywhere' ]; then cp -r '${PATH_PART}/custom_components/esp_anywhere' '$BACKUP_PATH' && echo 'Utworzono backup w $BACKUP_PATH'; fi"

    echo "Kopiowanie plików po SCP..."
    ssh "$HOST_PART" "mkdir -p '${PATH_PART}/custom_components/esp_anywhere'"
    scp -r "$SOURCE_DIR/"* "$HOST_PART:${PATH_PART}/custom_components/esp_anywhere/"

else
    BACKUP_PATH="${DEST}/custom_components/esp_anywhere_backup_$(date +%s)"

    if [ -d "${DEST}/custom_components/esp_anywhere" ]; then
        echo "Tworzę backup obecnej instalacji w $BACKUP_PATH..."
        cp -r "${DEST}/custom_components/esp_anywhere" "$BACKUP_PATH"
    fi

    echo "Kopiowanie plików lokalnie..."
    mkdir -p "${DEST}/custom_components/esp_anywhere"
    cp -r "$SOURCE_DIR/"* "${DEST}/custom_components/esp_anywhere/"
fi

echo ""
echo "Zakończono pomyślnie!"
echo "Upewnij się, że zrestartujesz instancję Home Assistant (Settings -> System -> Restart), aby załadować nową wersję."
