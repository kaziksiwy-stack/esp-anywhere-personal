#!/usr/bin/env python3
"""Create deterministic Ed25519-signed ESP Anywhere OTA manifests."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def compact_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build_manifest(args: argparse.Namespace) -> tuple[bytes, bytes, str]:
    firmware = args.firmware.read_bytes()
    digest = hashlib.sha256(firmware).hexdigest()
    if not SEMVER.fullmatch(args.version):
        raise ValueError("invalid version")
    if not IDENTIFIER.fullmatch(args.hardware_profile):
        raise ValueError("invalid hardware profile")
    if args.channel not in {"stable", "beta", "recovery"}:
        raise ValueError("invalid channel")
    if not args.firmware_url.startswith("https://") or "?" in args.firmware_url or "#" in args.firmware_url:
        raise ValueError("firmware URL must be secret-free HTTPS")
    private = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("signing key must be Ed25519")
    published_at = args.published_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {
        "build_id": args.build_id,
        "channel": args.channel,
        "chip_family": "ESP32-C3",
        "firmware": {"sha256": digest, "size": len(firmware), "url": args.firmware_url},
        "git_commit": args.git_commit,
        "hardware_profile": args.hardware_profile,
        "manifest_version": 1,
        "min_ota_bootstrap": args.min_ota_bootstrap,
        "min_protocol_version": args.min_protocol_version,
        "project": "esp-anywhere",
        "published_at": published_at,
        "recovery": bool(args.recovery),
        "summary": args.summary,
        "version": args.version,
    }
    payload_bytes = compact_json(payload)
    signature = private.sign(payload_bytes)
    envelope = {
        "schema_version": 2,
        "security": {
            "algorithm": "Ed25519",
            "key_id": args.key_id,
            "signature": base64.b64encode(signature).decode("ascii"),
        },
        "signed_payload": base64.b64encode(payload_bytes).decode("ascii"),
    }
    return compact_json(envelope) + b"\n", signature, digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--firmware-url", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "beta", "recovery"), required=True)
    parser.add_argument("--hardware-profile", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--min-protocol-version", default="1.0")
    parser.add_argument("--min-ota-bootstrap", type=int, default=1)
    parser.add_argument("--published-at")
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--signature-output", type=Path, required=True)
    parser.add_argument("--checksums-output", type=Path, required=True)
    args = parser.parse_args()
    manifest, signature, digest = build_manifest(args)
    args.output.write_bytes(manifest)
    args.signature_output.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    args.checksums_output.write_text(f"{digest}  {args.firmware.name}\n", encoding="ascii")


if __name__ == "__main__":
    main()
