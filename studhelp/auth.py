from __future__ import annotations

import hashlib
import secrets
import smtplib
from email.message import EmailMessage

from .config import Settings
from .storage import Storage


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def sanitize_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "createdAt": user["createdAt"],
    }


def validate_user_auth(payload: dict, with_name: bool) -> dict[str, str]:
    errors: dict[str, str] = {}
    if with_name:
        name = str(payload.get("name", "")).strip()
        if len(name) < 2:
            errors["name"] = "Укажите имя, минимум 2 символа."
    email = str(payload.get("email", "")).strip()
    password = str(payload.get("password", ""))
    if "@" not in email or "." not in email:
        errors["email"] = "Укажите корректную почту."
    if len(password) < 6:
        errors["password"] = "Пароль должен содержать минимум 6 символов."
    return errors


class AuthService:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage

    def register(self, payload: dict) -> tuple[dict, str]:
        user = self.storage.create_user(
            name=str(payload["name"]).strip(),
            email=str(payload["email"]).strip().lower(),
            password_hash=hash_password(str(payload["password"])),
        )
        token = secrets.token_hex(24)
        self.storage.create_session(token, int(user["id"]), self.settings.session_ttl_seconds)
        return sanitize_user(user), token

    def login(self, payload: dict) -> tuple[dict, str] | None:
        user = self.storage.get_user_by_email(str(payload["email"]).strip().lower())
        if user is None or user.get("passwordHash") != hash_password(str(payload["password"])):
            return None
        token = secrets.token_hex(24)
        self.storage.create_session(token, int(user["id"]), self.settings.session_ttl_seconds)
        return sanitize_user(user), token

    def get_user_by_session(self, session_token: str) -> dict | None:
        if not session_token:
            return None
        session = self.storage.get_session(session_token)
        if session is None:
            return None
        self.storage.touch_session(session_token, self.settings.session_ttl_seconds)
        user = self.storage.get_user_by_id(int(session["userId"]))
        return sanitize_user(user) if user else None

    def logout(self, session_token: str) -> None:
        if session_token:
            self.storage.delete_session(session_token)

    def request_password_reset(self, email: str) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.storage.create_password_reset(email, code, self.settings.reset_ttl_seconds)
        self._send_reset_email(email, code)
        return code

    def confirm_password_reset(self, email: str, code: str, password: str) -> bool:
        reset = self.storage.get_active_password_reset(email, code)
        if reset is None:
            return False
        self.storage.mark_password_reset_used(int(reset["id"]))
        return self.storage.update_user_password(email, hash_password(password))

    def _send_reset_email(self, email: str, code: str) -> None:
        if self.settings.email_sender is not None:
            self.settings.email_sender(email, code)
            return
        if not self.settings.smtp_host or not self.settings.smtp_from:
            raise RuntimeError("Почтовый сервер не настроен.")
        message = EmailMessage()
        message["Subject"] = "Код восстановления пароля"
        message["From"] = self.settings.smtp_from
        message["To"] = email
        message.set_content(f"Ваш код восстановления пароля: {code}")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as client:
            client.starttls()
            if self.settings.smtp_username:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
            client.send_message(message)
