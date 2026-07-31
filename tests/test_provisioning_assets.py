import json
from pathlib import Path
import re
import subprocess
import sys
import types
import unittest

http_module = types.ModuleType("homeassistant.components.http")
http_module.HomeAssistantView = object
sys.modules.setdefault("homeassistant.components", types.ModuleType("homeassistant.components"))
sys.modules["homeassistant.components.http"] = http_module

from custom_components.esp_anywhere.provisioning import generate_device_id, load_profiles

ROOT = Path(__file__).parents[1]


class ProvisioningAssetTests(unittest.TestCase):
    def test_generated_ids_are_safe_and_collision_resistant(self):
        first = generate_device_id("Sterownik garażu")
        second = generate_device_id("Sterownik garażu")
        self.assertRegex(first, r"^[a-z0-9][a-z0-9_-]{2,63}$")
        self.assertNotEqual(first, second)

    def test_profile_catalog_has_required_fields(self):
        required = {"id", "name", "platform", "board", "flash_layout", "led_pin", "led_active_low", "usb_mode", "firmware_artifact"}
        profiles = load_profiles()
        self.assertEqual([item["id"] for item in profiles], ["esp32-c3-devkitm-1"])
        self.assertTrue(required.issubset(profiles[0]))

    def test_web_page_keeps_secrets_out_of_url_and_logs(self):
        html = (ROOT / "worker/src/provision-v2.html").read_text()
        handoff = (ROOT / "custom_components/esp_anywhere/static/provision.html").read_text()
        self.assertNotIn("ADMIN_TOKEN", html)
        self.assertNotIn("console.log", html)
        self.assertNotRegex(html, r"activation_code=.*[?&]")
        self.assertIn("navigator.serial.requestPort", html)
        self.assertIn("window.isSecureContext", html)
        self.assertIn("NotFoundError", html)
        self.assertIn("factory_reset", html)
        self.assertIn("confirm(", html)
        self.assertIn("reader.releaseLock()", html)
        self.assertIn("esp-anywhere-config", handoff)
        self.assertIn("event.origin!==provisionOrigin", handoff)
        self.assertNotIn("activation_code", handoff)

    def test_inline_javascript_is_syntactically_valid(self):
        for relative in ("custom_components/esp_anywhere/static/provision.html", "worker/src/provision-v2.html"):
            html = (ROOT / relative).read_text()
            scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
            self.assertEqual(len(scripts), 1)
            subprocess.run(["node", "--check", "-"], input=scripts[0], text=True, check=True, capture_output=True)

    def test_firmware_has_factory_reset_and_erases_activation_after_claim(self):
        source = (ROOT / "esp32_client/src/main.cpp").read_text()
        self.assertIn('type == "factory_reset"', source)
        self.assertIn('preferences.remove("activation")', source)
        provisioning = (ROOT / "custom_components/esp_anywhere/provisioning.py").read_text()
        self.assertIn('item.activation_code = ""', provisioning)
        self.assertIn('preferences.clear()', source)


if __name__ == "__main__":
    unittest.main()
