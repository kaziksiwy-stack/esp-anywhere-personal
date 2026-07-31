import argparse
import base64
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.sign_ota_manifest import build_manifest
from custom_components.esp_anywhere.manifest import parse_and_verify_manifest


class OtaManifestV2Test(unittest.TestCase):
    def make(self):
        temporary = tempfile.TemporaryDirectory(); root = Path(temporary.name)
        private = Ed25519PrivateKey.generate()
        key_file = root / "key.pem"
        key_file.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        firmware = root / "firmware.bin"; firmware.write_bytes(b"signed firmware fixture")
        args = argparse.Namespace(private_key=key_file, key_id="test-2026", firmware=firmware,
            firmware_url="https://raw.githubusercontent.com/example/repo/a" + "0" * 39 + "/firmware.bin",
            version="0.3.2", channel="beta", hardware_profile="esp32-c3-devkitm-1",
            git_commit="a" * 40, build_id="test-build", summary="test", min_protocol_version="1.0",
            min_ota_bootstrap=1, published_at="2026-07-31T20:00:00Z", recovery=False)
        manifest, _, _ = build_manifest(args)
        public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        return temporary, manifest, public

    def test_valid_v2_and_tampering(self):
        temporary, manifest, public = self.make()
        with temporary:
            parsed = parse_and_verify_manifest(manifest, trusted_keys={"test-2026": public}, expected_hardware_profile="esp32-c3-devkitm-1")
            self.assertEqual("0.3.2", parsed.version)
            outer = json.loads(manifest); payload = bytearray(base64.b64decode(outer["signed_payload"])); payload[-2] ^= 1
            outer["signed_payload"] = base64.b64encode(payload).decode()
            with self.assertRaisesRegex(ValueError, "signature"):
                parse_and_verify_manifest(json.dumps(outer).encode(), trusted_keys={"test-2026": public}, expected_hardware_profile="esp32-c3-devkitm-1")

    def test_wrong_profile_and_key(self):
        temporary, manifest, public = self.make()
        with temporary:
            with self.assertRaisesRegex(ValueError, "profile"):
                parse_and_verify_manifest(manifest, trusted_keys={"test-2026": public}, expected_hardware_profile="other-profile")
            with self.assertRaisesRegex(ValueError, "untrusted"):
                parse_and_verify_manifest(manifest, trusted_keys={"other": public}, expected_hardware_profile="esp32-c3-devkitm-1")


if __name__ == "__main__": unittest.main()
