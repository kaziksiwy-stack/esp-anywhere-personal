"""Signed firmware manifest validation for ESP Anywhere."""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import rfc8785

from .protocol import PROTOCOL_VERSION, ProtocolError

SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class FirmwareManifest:
    version: str
    protocol_version: str
    channel: str
    hardware_profile: str
    chip_family: str
    firmware_url: str
    firmware_size: int
    firmware_sha256: str
    key_id: str
    signature: str
    published_at: str
    release_url: str | None = None
    summary: str | None = None
    min_ota_bootstrap: int = 1
    recovery: bool = False
    algorithm: str = "Ed25519"


def parse_and_verify_manifest(document: bytes, *, expected_hardware_profile: str,
                              trusted_keys: dict[str, str] | None = None,
                              trusted_key_id: str | None = None,
                              trusted_public_key: str | None = None) -> FirmwareManifest:
    """Parse and authenticate either legacy JCS schema 1 or byte-payload schema 2."""
    if len(document) > 64 * 1024:
        raise ProtocolError("Manifest exceeds 64 KiB")
    try:
        outer = json.loads(document.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ProtocolError("Manifest is not a UTF-8 JSON object") from err
    if not isinstance(outer, dict):
        raise ProtocolError("Manifest root must be an object")
    keys = dict(trusted_keys or {})
    if trusted_key_id and trusted_public_key:
        keys.setdefault(trusted_key_id, trusted_public_key)
    if outer.get("schema_version") == 2:
        raw, key_id, signature = _verify_v2(outer, keys)
    elif outer.get("schema_version") == 1:
        security = outer.get("security")
        if not isinstance(security, dict):
            raise ProtocolError("Manifest security must be an object")
        key_id = _required_string(security, "key_id", 64)
        signature = _required_string(security, "signature", 128)
        public = keys.get(key_id)
        _require(public is not None, "Manifest uses an untrusted signing key")
        _verify_v1(outer, signature, public)
        raw = outer
    else:
        raise ProtocolError("Unsupported manifest schema")
    return _validate_signed_payload(raw, key_id, signature, expected_hardware_profile)


def _verify_v2(outer: dict[str, Any], keys: dict[str, str]) -> tuple[dict[str, Any], str, str]:
    security = outer.get("security")
    if not isinstance(security, dict):
        raise ProtocolError("Manifest security must be an object")
    _require(_required_string(security, "algorithm", 16) == "Ed25519", "Unsupported signature algorithm")
    key_id = _required_string(security, "key_id", 64)
    signature = _required_string(security, "signature", 128)
    public = keys.get(key_id)
    _require(public is not None, "Manifest uses an untrusted signing key")
    signed_payload = _required_string(outer, "signed_payload", 48 * 1024)
    try:
        payload_bytes = base64.b64decode(signed_payload, validate=True)
        signature_bytes = base64.b64decode(signature, validate=True)
        key_bytes = base64.b64decode(public, validate=True)
        if len(key_bytes) != 32 or len(signature_bytes) != 64:
            raise ProtocolError("Invalid Ed25519 key or signature length")
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature_bytes, payload_bytes)
        raw = json.loads(payload_bytes.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, InvalidSignature) as err:
        raise ProtocolError("Invalid manifest signature or signed payload") from err
    if not isinstance(raw, dict):
        raise ProtocolError("Signed payload must be an object")
    _require(raw.get("manifest_version") == 1, "Unsupported signed payload version")
    return raw, key_id, signature


def _verify_v1(raw: dict[str, Any], signature: str, public_key: str) -> None:
    unsigned = json.loads(json.dumps(raw)); unsigned["security"].pop("signature", None)
    try:
        canonical = rfc8785.dumps(unsigned)
        key_bytes = base64.b64decode(public_key, validate=True)
        signature_bytes = base64.b64decode(signature, validate=True)
        if len(key_bytes) != 32 or len(signature_bytes) != 64:
            raise ProtocolError("Invalid Ed25519 key or signature length")
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature_bytes, canonical)
    except (rfc8785.CanonicalizationError, binascii.Error, ValueError, InvalidSignature) as err:
        raise ProtocolError("Invalid manifest signature") from err


def _validate_signed_payload(raw: dict[str, Any], key_id: str, signature: str,
                             expected_hardware_profile: str) -> FirmwareManifest:
    _require(raw.get("project") == "esp-anywhere", "Wrong manifest project")
    version = _required_string(raw, "version", 64)
    _require(SEMVER_PATTERN.fullmatch(version) is not None, "Invalid firmware SemVer")
    protocol = raw.get("min_protocol_version", raw.get("protocol_version"))
    _require(protocol == PROTOCOL_VERSION, "Incompatible protocol")
    channel = _required_string(raw, "channel", 16)
    _require(channel in {"stable", "beta", "recovery"}, "Invalid release channel")
    recovery = raw.get("recovery", False)
    _require(isinstance(recovery, bool), "Invalid recovery flag")
    _require(not recovery or channel == "recovery", "Recovery requires recovery channel")
    profile = _required_string(raw, "hardware_profile", 64)
    _require(profile == expected_hardware_profile, "Wrong hardware profile")
    chip = _required_string(raw, "chip_family", 16)
    _require(chip == "ESP32-C3", "Unsupported chip family")
    commit = _required_string(raw, "git_commit", 40)
    _require(GIT_COMMIT_PATTERN.fullmatch(commit) is not None, "Invalid git commit")
    _required_string(raw, "build_id", 128)
    published = _required_string(raw, "published_at", 64)
    try: datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError as err: raise ProtocolError("Invalid published_at") from err
    firmware = raw.get("firmware")
    if not isinstance(firmware, dict): raise ProtocolError("Firmware must be an object")
    url = _required_string(firmware, "url", 1024)
    _require(url.startswith("https://"), "Firmware URL must use HTTPS")
    size = firmware.get("size")
    _require(isinstance(size, int) and 0 < size <= 2 * 1024 * 1024, "Invalid firmware size")
    sha = _required_string(firmware, "sha256", 64)
    _require(SHA256_PATTERN.fullmatch(sha) is not None, "Invalid SHA-256")
    bootstrap = raw.get("min_ota_bootstrap", 1)
    _require(isinstance(bootstrap, int) and 1 <= bootstrap <= 65535, "Invalid OTA bootstrap version")
    return FirmwareManifest(version, protocol, channel, profile, chip, url, size, sha, key_id,
        signature, published, _optional_https(raw, "release_url"), _optional_string(raw, "summary", 1024),
        bootstrap, recovery, "Ed25519")


def version_is_newer(candidate: str, installed: str) -> bool:
    return _semver_key(candidate) > _semver_key(installed)


def validate_manifest_url(url: str, allowed_host: str) -> None:
    parsed = urlsplit(url)
    try: port = parsed.port
    except ValueError as err: raise ProtocolError("Manifest URL contains an invalid port") from err
    if parsed.scheme != "https" or parsed.hostname is None or parsed.hostname.lower() != allowed_host.lower() or parsed.username is not None or parsed.password is not None or port not in (None, 443) or not parsed.path.startswith("/"):
        raise ProtocolError("Manifest URL is outside the allowed firmware host")


def _semver_key(value: str) -> tuple:
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None: raise ProtocolError("Invalid firmware SemVer")
    prerelease = match.group(4)
    pre_key = ((1, ""),) if prerelease is None else ((0, ""), *[(0, int(p)) if p.isdigit() else (1, p) for p in prerelease.split(".")])
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), pre_key)


def _required_string(payload: dict[str, Any], key: str, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum: raise ProtocolError(f"Invalid or missing {key}")
    return value


def _optional_string(payload: dict[str, Any], key: str, maximum: int) -> str | None:
    value = payload.get(key)
    if value is None: return None
    if not isinstance(value, str) or len(value) > maximum: raise ProtocolError(f"Invalid {key}")
    return value


def _optional_https(payload: dict[str, Any], key: str) -> str | None:
    value = _optional_string(payload, key, 1024)
    if value is not None and not value.startswith("https://"): raise ProtocolError(f"{key} must use HTTPS")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition: raise ProtocolError(message)
