Import("env")
import json
from pathlib import Path
path = Path(env.subst("$PROJECT_DIR")).parent / "custom_components" / "esp_anywhere" / "device_profiles.json"
profile = json.loads(path.read_text(encoding="utf-8"))["profiles"][0]
env.Append(CPPDEFINES=[("ESP_ANYWHERE_PROFILE_ID", f"\\\"{profile['id']}\\\""), ("ESP_ANYWHERE_LED_PIN", profile["led_pin"]), ("ESP_ANYWHERE_LED_ACTIVE_LOW", int(profile["led_active_low"]))])

home_path = Path.home()
env.Append(CCFLAGS=[f"-ffile-prefix-map={home_path}=/build", f"-fmacro-prefix-map={home_path}=/build"])
