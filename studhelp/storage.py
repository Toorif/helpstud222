from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def initialize(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        for file_path, default in (
            (self.settings.data_dir / "requests.json", "[]"),
            (self.settings.data_dir / "reviews.json", "[]"),
            (self.settings.data_dir / "works.json", "[]"),
            (self.settings.data_dir / "users.json", "[]"),
            (self.settings.data_dir / "sessions.json", "[]"),
            (self.settings.data_dir / "messages.json", "[]"),
            (self.settings.data_dir / "password_resets.json", "[]"),
        ):
            if not file_path.exists():
                file_path.write_text(default, encoding="utf-8")
        self._initialize_database()
        self._migrate_legacy_json()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.settings.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_by_admin INTEGER NOT NULL DEFAULT 0,
                    read_by_user INTEGER NOT NULL DEFAULT 0,
                    attachment_name TEXT,
                    attachment_content_type TEXT,
                    attachment_path TEXT,
                    attachment_size INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS password_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    code TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    action TEXT NOT NULL,
                    key TEXT NOT NULL,
                    window_started_at TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY(action, key)
                );
                """
            )

    def _load_json_list(self, file_path: Path) -> list[dict]:
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            file_path.write_text("[]", encoding="utf-8")
            return []
        return data if isinstance(data, list) else []

    def _write_json_list(self, file_path: Path, entries: list[dict]) -> None:
        file_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    def _table_count(self, table_name: str) -> int:
        with self._connect() as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"]) if row else 0

    def _migrate_legacy_json(self) -> None:
        if self._table_count("users") == 0:
            self._migrate_users()
        if self._table_count("user_sessions") == 0:
            self._migrate_sessions()
        if self._table_count("messages") == 0:
            self._migrate_messages()
        if self._table_count("password_resets") == 0:
            self._migrate_password_resets()

    def _migrate_users(self) -> None:
        items = self._load_json_list(self.settings.data_dir / "users.json")
        if not items:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO users (id, name, email, password_hash, created_at)
                VALUES (:id, :name, :email, :password_hash, :created_at)
                """,
                [
                    {
                        "id": int(item["id"]),
                        "name": str(item.get("name", "")).strip(),
                        "email": str(item.get("email", "")).strip().lower(),
                        "password_hash": item.get("passwordHash", ""),
                        "created_at": item.get("createdAt", to_iso(utcnow())),
                    }
                    for item in items
                ],
            )

    def _migrate_sessions(self) -> None:
        items = self._load_json_list(self.settings.data_dir / "sessions.json")
        if not items:
            return
        with self._connect() as connection:
            for item in items:
                created_at = str(item.get("createdAt", to_iso(utcnow())))
                expires_at = to_iso(from_iso(created_at) + timedelta(seconds=self.settings.session_ttl_seconds))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_sessions (token, user_id, created_at, expires_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item.get("token", ""),
                        int(item.get("userId", 0)),
                        created_at,
                        expires_at,
                        created_at,
                    ),
                )

    def _migrate_messages(self) -> None:
        items = self._load_json_list(self.settings.data_dir / "messages.json")
        if not items:
            return
        with self._connect() as connection:
            for item in items:
                attachment = item.get("attachment") if isinstance(item.get("attachment"), dict) else {}
                connection.execute(
                    """
                    INSERT OR IGNORE INTO messages (
                        id, user_id, sender, text, created_at, read_by_admin, read_by_user,
                        attachment_name, attachment_content_type, attachment_path, attachment_size
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(item.get("id", 0)),
                        int(item.get("userId", 0)),
                        item.get("sender", "user"),
                        str(item.get("text", "")),
                        item.get("createdAt", to_iso(utcnow())),
                        1 if item.get("readByAdmin", False) else 0,
                        1 if item.get("readByUser", False) else 0,
                        attachment.get("name"),
                        attachment.get("contentType"),
                        attachment.get("path"),
                        attachment.get("size"),
                    ),
                )

    def _migrate_password_resets(self) -> None:
        items = self._load_json_list(self.settings.data_dir / "password_resets.json")
        if not items:
            return
        with self._connect() as connection:
            for item in items:
                created_at = str(item.get("createdAt", to_iso(utcnow())))
                expires_at = to_iso(from_iso(created_at) + timedelta(seconds=self.settings.reset_ttl_seconds))
                connection.execute(
                    """
                    INSERT INTO password_resets (email, code, created_at, expires_at, used_at, attempt_count)
                    VALUES (?, ?, ?, ?, NULL, 0)
                    """,
                    (str(item.get("email", "")).lower(), str(item.get("code", "")), created_at, expires_at),
                )

    def load_requests(self) -> list[dict]:
        return self._load_json_list(self.settings.data_dir / "requests.json")

    def write_requests(self, entries: list[dict]) -> None:
        self._write_json_list(self.settings.data_dir / "requests.json", entries)

    def load_reviews(self) -> list[dict]:
        return self._load_json_list(self.settings.data_dir / "reviews.json")

    def write_reviews(self, entries: list[dict]) -> None:
        self._write_json_list(self.settings.data_dir / "reviews.json", entries)

    def load_works(self) -> list[dict]:
        return self._load_json_list(self.settings.data_dir / "works.json")

    def write_works(self, entries: list[dict]) -> None:
        self._write_json_list(self.settings.data_dir / "works.json", entries)

    def next_json_id(self, entries: list[dict]) -> int:
        return max((int(item.get("id", 0)) for item in entries), default=0) + 1

    def get_user_by_email(self, email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name, email, password_hash, created_at FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        return self._user_row_to_dict(row)

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name, email, password_hash, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._user_row_to_dict(row)

    def create_user(self, name: str, email: str, password_hash: str) -> dict:
        created_at = to_iso(utcnow())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (name, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name.strip(), email.strip().lower(), password_hash, created_at),
            )
            user_id = int(cursor.lastrowid)
        return self.get_user_by_id(user_id) or {
            "id": user_id,
            "name": name.strip(),
            "email": email.strip().lower(),
            "passwordHash": password_hash,
            "createdAt": created_at,
        }

    def update_user_password(self, email: str, password_hash: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET password_hash = ? WHERE email = ?",
                (password_hash, email.strip().lower()),
            )
        return cursor.rowcount > 0

    def create_session(self, token: str, user_id: int, ttl_seconds: int) -> dict:
        now = utcnow()
        created_at = to_iso(now)
        expires_at = to_iso(now + timedelta(seconds=ttl_seconds))
        with self._connect() as connection:
            connection.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            connection.execute(
                """
                INSERT INTO user_sessions (token, user_id, created_at, expires_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token, user_id, created_at, expires_at, created_at),
            )
        return {"token": token, "userId": user_id, "createdAt": created_at, "expiresAt": expires_at}

    def get_session(self, token: str) -> dict | None:
        self.purge_expired_sessions()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT token, user_id, created_at, expires_at, last_seen_at FROM user_sessions WHERE token = ?",
                (token,),
            ).fetchone()
        if not row:
            return None
        return {
            "token": row["token"],
            "userId": int(row["user_id"]),
            "createdAt": row["created_at"],
            "expiresAt": row["expires_at"],
            "lastSeenAt": row["last_seen_at"],
        }

    def touch_session(self, token: str, ttl_seconds: int) -> None:
        now = utcnow()
        with self._connect() as connection:
            connection.execute(
                "UPDATE user_sessions SET last_seen_at = ?, expires_at = ? WHERE token = ?",
                (to_iso(now), to_iso(now + timedelta(seconds=ttl_seconds)), token),
            )

    def delete_session(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM user_sessions WHERE token = ?", (token,))

    def purge_expired_sessions(self) -> None:
        now = to_iso(utcnow())
        with self._connect() as connection:
            connection.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))

    def create_password_reset(self, email: str, code: str, ttl_seconds: int) -> None:
        now = utcnow()
        with self._connect() as connection:
            connection.execute("DELETE FROM password_resets WHERE email = ? AND used_at IS NULL", (email.strip().lower(),))
            connection.execute(
                """
                INSERT INTO password_resets (email, code, created_at, expires_at, used_at, attempt_count)
                VALUES (?, ?, ?, ?, NULL, 0)
                """,
                (
                    email.strip().lower(),
                    code,
                    to_iso(now),
                    to_iso(now + timedelta(seconds=ttl_seconds)),
                ),
            )

    def get_active_password_reset(self, email: str, code: str) -> dict | None:
        self.purge_expired_password_resets()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, code, created_at, expires_at, used_at, attempt_count
                FROM password_resets
                WHERE email = ? AND code = ? AND used_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (email.strip().lower(), code.strip()),
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def increment_password_reset_attempt(self, reset_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE password_resets SET attempt_count = attempt_count + 1 WHERE id = ?",
                (reset_id,),
            )

    def mark_password_reset_used(self, reset_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE password_resets SET used_at = ? WHERE id = ?",
                (to_iso(utcnow()), reset_id),
            )

    def purge_expired_password_resets(self) -> None:
        now = to_iso(utcnow())
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM password_resets WHERE (expires_at <= ? AND used_at IS NULL) OR used_at IS NOT NULL",
                (now,),
            )

    def consume_rate_limit(self, action: str, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = utcnow()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT action, key, window_started_at, count FROM rate_limits WHERE action = ? AND key = ?",
                (action, key),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO rate_limits (action, key, window_started_at, count) VALUES (?, ?, ?, 1)",
                    (action, key, to_iso(now)),
                )
                return True, 0
            window_started_at = from_iso(row["window_started_at"])
            if now - window_started_at >= timedelta(seconds=window_seconds):
                connection.execute(
                    "UPDATE rate_limits SET window_started_at = ?, count = 1 WHERE action = ? AND key = ?",
                    (to_iso(now), action, key),
                )
                return True, 0
            if int(row["count"]) >= limit:
                retry_after = max(1, window_seconds - int((now - window_started_at).total_seconds()))
                return False, retry_after
            connection.execute(
                "UPDATE rate_limits SET count = count + 1 WHERE action = ? AND key = ?",
                (action, key),
            )
            return True, 0

    def create_message(self, user_id: int, sender: str, text: str, attachment: dict | None = None) -> dict:
        created_at = to_iso(utcnow())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (
                    user_id, sender, text, created_at, read_by_admin, read_by_user,
                    attachment_name, attachment_content_type, attachment_path, attachment_size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    sender,
                    text.strip(),
                    created_at,
                    1 if sender == "admin" else 0,
                    1 if sender == "user" else 0,
                    attachment.get("name") if attachment else None,
                    attachment.get("contentType") if attachment else None,
                    attachment.get("path") if attachment else None,
                    attachment.get("size") if attachment else None,
                ),
            )
            message_id = int(cursor.lastrowid)
        return self.get_message(message_id) or {}

    def get_message(self, message_id: int) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, sender, text, created_at, read_by_admin, read_by_user,
                       attachment_name, attachment_content_type, attachment_path, attachment_size
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        return self._message_row_to_dict(row)

    def list_user_messages(self, user_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, sender, text, created_at, read_by_admin, read_by_user,
                       attachment_name, attachment_content_type, attachment_path, attachment_size
                FROM messages
                WHERE user_id = ?
                ORDER BY id ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._message_row_to_dict(row) for row in rows if row]

    def mark_messages_read(self, user_id: int, reader: str) -> None:
        with self._connect() as connection:
            if reader == "admin":
                connection.execute(
                    "UPDATE messages SET read_by_admin = 1 WHERE user_id = ? AND sender = 'user' AND read_by_admin = 0",
                    (user_id,),
                )
            if reader == "user":
                connection.execute(
                    "UPDATE messages SET read_by_user = 1 WHERE user_id = ? AND sender = 'admin' AND read_by_user = 0",
                    (user_id,),
                )

    def count_unread_for_admin(self, user_id: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE user_id = ? AND sender = 'user' AND read_by_admin = 0",
                (user_id,),
            ).fetchone()
        return int(row["count"]) if row else 0

    def list_admin_chats(self) -> list[dict]:
        chats: list[dict] = []
        with self._connect() as connection:
            user_rows = connection.execute(
                "SELECT id, name, email, created_at FROM users ORDER BY created_at DESC"
            ).fetchall()
            for user_row in user_rows:
                message_row = connection.execute(
                    """
                    SELECT id, user_id, sender, text, created_at, read_by_admin, read_by_user,
                           attachment_name, attachment_content_type, attachment_path, attachment_size
                    FROM messages
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (int(user_row["id"]),),
                ).fetchone()
                count_row = connection.execute(
                    "SELECT COUNT(*) AS count FROM messages WHERE user_id = ?",
                    (int(user_row["id"]),),
                ).fetchone()
                chats.append(
                    {
                        "user": {
                            "id": int(user_row["id"]),
                            "name": user_row["name"],
                            "email": user_row["email"],
                            "createdAt": user_row["created_at"],
                        },
                        "lastMessage": self._message_row_to_dict(message_row),
                        "messageCount": int(count_row["count"]) if count_row else 0,
                        "unreadCount": self.count_unread_for_admin(int(user_row["id"])),
                    }
                )
        chats.sort(
            key=lambda item: item["lastMessage"]["createdAt"] if item["lastMessage"] else item["user"]["createdAt"],
            reverse=True,
        )
        return chats

    def _user_row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "email": row["email"],
            "passwordHash": row["password_hash"],
            "createdAt": row["created_at"],
        }

    def _message_row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        item = {
            "id": int(row["id"]),
            "userId": int(row["user_id"]),
            "sender": row["sender"],
            "text": row["text"],
            "createdAt": row["created_at"],
            "readByAdmin": bool(row["read_by_admin"]),
            "readByUser": bool(row["read_by_user"]),
        }
        if row["attachment_path"] and row["attachment_name"]:
            item["attachment"] = {
                "name": row["attachment_name"],
                "contentType": row["attachment_content_type"],
                "path": row["attachment_path"],
                "size": row["attachment_size"],
            }
        return item
