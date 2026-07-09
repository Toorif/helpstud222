from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class Settings:
    root_dir: Path
    static_dir: Path
    data_dir: Path
    uploads_dir: Path
    database_path: Path
    max_request_size: int = 8 * 1024 * 1024
    max_attachment_size: int = 5 * 1024 * 1024
    admin_username: str = "admin"
    admin_password: str = "change-me-please"
    session_cookie_name: str = "studhelp_session"
    session_ttl_seconds: int = 7 * 24 * 60 * 60
    reset_ttl_seconds: int = 15 * 60
    login_rate_limit_count: int = 10
    login_rate_limit_window_seconds: int = 15 * 60
    reset_request_rate_limit_count: int = 5
    reset_request_rate_limit_window_seconds: int = 60 * 60
    reset_confirm_rate_limit_count: int = 10
    reset_confirm_rate_limit_window_seconds: int = 30 * 60
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    email_sender: Callable[[str, str], None] | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, root_dir: Path) -> "Settings":
        data_dir = root_dir / "data"
        smtp_username = os.getenv("SMTP_USERNAME", "")
        return cls(
            root_dir=root_dir,
            static_dir=root_dir / "static",
            data_dir=data_dir,
            uploads_dir=root_dir / "uploads",
            database_path=data_dir / "app.sqlite3",
            admin_username=os.getenv("ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("ADMIN_PASSWORD", "change-me-please"),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=smtp_username,
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from=os.getenv("SMTP_FROM", smtp_username),
        )
