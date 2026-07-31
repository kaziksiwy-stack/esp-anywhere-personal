"""Canonical relay endpoint construction."""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit


def _relay_base(value: str) -> tuple[str, str]:
    """Validate a relay base URL and return its scheme and authority."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https", "ws", "wss"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("relay_url must be an HTTP(S) or WS(S) base URL")
    return parsed.scheme, parsed.netloc


def claim_url(relay_url: str) -> str:
    """Build the HTTP claim endpoint from a relay base URL."""
    scheme, authority = _relay_base(relay_url)
    http_scheme = "https" if scheme in {"https", "wss"} else "http"
    return urlunsplit((http_scheme, authority, "/claim", "", ""))


def websocket_url(relay_url: str, installation_id: str) -> str:
    """Build the Home Assistant WebSocket endpoint from a relay base URL."""
    scheme, authority = _relay_base(relay_url)
    ws_scheme = "wss" if scheme in {"https", "wss"} else "ws"
    return urlunsplit((
        ws_scheme, authority, "/ws",
        urlencode({"role": "home_assistant", "installation_id": installation_id}), "",
    ))
