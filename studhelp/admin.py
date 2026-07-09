from __future__ import annotations

import base64

from .config import Settings


def is_admin_authorized(header: str, settings: Settings) -> bool:
    if not header.startswith("Basic "):
        return False
    token = header.removeprefix("Basic ").strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    return bool(separator) and username == settings.admin_username and password == settings.admin_password
