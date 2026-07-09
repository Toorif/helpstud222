from __future__ import annotations

import base64
import secrets
from pathlib import Path

from .config import Settings
from .storage import Storage


class ChatService:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage

    def store_attachment(self, payload: dict) -> dict:
        filename = str(payload.get("name", "file")).strip() or "file"
        content_type = str(payload.get("contentType", "application/octet-stream")).strip() or "application/octet-stream"
        content_base64 = str(payload.get("contentBase64", ""))
        raw_bytes = base64.b64decode(content_base64.encode("utf-8"), validate=True)
        if len(raw_bytes) > self.settings.max_attachment_size:
            raise ValueError("Файл слишком большой.")
        suffix = Path(filename).suffix or ""
        stored_name = f"{secrets.token_hex(12)}{suffix}"
        stored_path = self.settings.uploads_dir / stored_name
        stored_path.write_bytes(raw_bytes)
        return {
            "name": filename,
            "contentType": content_type,
            "path": f"/uploads/{stored_name}",
            "size": len(raw_bytes),
        }

    def create_message(self, user_id: int, sender: str, text: str, attachment_payload: dict | None = None) -> dict:
        attachment = None
        if isinstance(attachment_payload, dict) and attachment_payload.get("contentBase64"):
            attachment = self.store_attachment(attachment_payload)
        return self.storage.create_message(user_id, sender, text, attachment)

    def get_user_messages(self, user_id: int) -> list[dict]:
        return self.storage.list_user_messages(user_id)

    def mark_messages_read(self, user_id: int, reader: str) -> None:
        self.storage.mark_messages_read(user_id, reader)

    def get_admin_chats(self) -> list[dict]:
        return self.storage.list_admin_chats()
