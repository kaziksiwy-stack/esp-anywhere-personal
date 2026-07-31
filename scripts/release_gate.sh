#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
(cd worker && npm test && npm run typecheck)
python3 -m compileall -q custom_components tests
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/*.sh
./scripts/provision_esp32.sh --dry-run
ha_stage="$(mktemp -d /tmp/esp-anywhere-ha-gate.XXXXXX)"
./scripts/install_to_haos.sh "$ha_stage"
test -f "$ha_stage/custom_components/esp_anywhere/manifest.json"
private_config="$(mktemp /tmp/esp-anywhere-config-gate.XXXXXX)"
cp esp32_client/include/config.h "$private_config"
restore_config() { cp "$private_config" esp32_client/include/config.h; }
trap restore_config EXIT
cp esp32_client/include/config.example.h esp32_client/include/config.h
export SOURCE_DATE_EPOCH=1767225600
/home/piotr/.platformio/penv/bin/platformio run --project-dir esp32_client --target clean
/home/piotr/.platformio/penv/bin/platformio run --project-dir esp32_client
cmp esp32_client/.pio/build/esp32-c3-devkitm-1/firmware.factory.bin custom_components/esp_anywhere/static/firmware.factory.bin
cmp custom_components/esp_anywhere/static/firmware.factory.bin worker/src/firmware-d81692.bin
restore_config
trap - EXIT
git diff --check
if git ls-files | grep -Eq '(^|/)(config\.h|\.dev\.vars)$'; then
  echo 'Tracked private configuration detected.' >&2; exit 1
fi
if git grep -n -E '192\.168\.|100\.110\.|first-real-test|esp32_c3_001' -- ':!tests/**' ':!worker/tests/**'; then
  echo 'Local address or personal test identifier detected.' >&2; exit 1
fi
echo 'release gate: PASS'
