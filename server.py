from __future__ import annotations

import json
import mimetypes
import os
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from studhelp.admin import is_admin_authorized
from studhelp.auth import AuthService, validate_user_auth
from studhelp.chat import ChatService
from studhelp.config import Settings
from studhelp.reviews import ReviewService, parse_iso_date
from studhelp.storage import Storage


ROOT_DIR = Path(__file__).resolve().parent


class Application:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = Storage(settings)
        self.auth = AuthService(settings, self.storage)
        self.chat = ChatService(settings, self.storage)
        self.reviews = ReviewService(self.storage)

    def initialize(self) -> None:
        self.storage.initialize()


def create_handler(app: Application):
    class AppHandler(BaseHTTPRequestHandler):
        server_version = "HelpStudent/2.0"

        def do_GET(self) -> None:
            self._response_sent = False
            parsed = urlparse(self.path)

            if parsed.path == "/api/health":
                self._send_json({"status": "ok"})
                return

            if parsed.path == "/api/requests":
                self._require_admin()
                if self._response_sent:
                    return
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0].strip()
                task_type = params.get("taskType", [""])[0].strip()
                date_from = parse_iso_date(params.get("dateFrom", [""])[0].strip()) if params.get("dateFrom") else None
                date_to = parse_iso_date(params.get("dateTo", [""])[0].strip()) if params.get("dateTo") else None
                items = app.reviews.filter_requests(query, task_type, date_from, date_to)
                self._send_json({"ok": True, "items": items})
                return

            if parsed.path == "/api/reviews":
                self._send_json({"ok": True, "items": app.reviews.public_reviews()})
                return

            if parsed.path == "/api/works":
                self._send_json({"ok": True, "items": app.reviews.public_works()})
                return

            if parsed.path == "/api/auth/me":
                user = self._require_user()
                if self._response_sent or user is None:
                    return
                self._send_json({"ok": True, "user": user})
                return

            if parsed.path == "/api/chat/messages":
                user = self._require_user()
                if self._response_sent or user is None:
                    return
                app.chat.mark_messages_read(int(user["id"]), "user")
                self._send_json({"ok": True, "items": app.chat.get_user_messages(int(user["id"]))})
                return

            if parsed.path == "/api/admin/chats":
                self._require_admin()
                if self._response_sent:
                    return
                self._send_json({"ok": True, "items": app.chat.get_admin_chats()})
                return

            if parsed.path.startswith("/api/admin/chats/") and parsed.path.endswith("/messages"):
                self._require_admin()
                if self._response_sent:
                    return
                user_id_raw = parsed.path.removeprefix("/api/admin/chats/").removesuffix("/messages").strip("/")
                if not user_id_raw.isdigit():
                    self._send_json({"ok": False, "message": "Некорректный идентификатор пользователя."}, status=HTTPStatus.BAD_REQUEST)
                    return
                user = app.storage.get_user_by_id(int(user_id_raw))
                if user is None:
                    self._send_json({"ok": False, "message": "Пользователь не найден."}, status=HTTPStatus.NOT_FOUND)
                    return
                app.chat.mark_messages_read(int(user_id_raw), "admin")
                self._send_json({"ok": True, "items": app.chat.get_user_messages(int(user_id_raw))})
                return

            if parsed.path == "/api/admin/reviews":
                self._require_admin()
                if self._response_sent:
                    return
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0].strip()
                status = params.get("status", [""])[0].strip()
                items = app.reviews.filter_reviews(query, status)
                self._send_json({"ok": True, "items": items})
                return

            if parsed.path == "/api/admin/works":
                self._require_admin()
                if self._response_sent:
                    return
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0].strip()
                self._send_json({"ok": True, "items": app.reviews.filter_works(query)})
                return

            self._serve_static(parsed.path)

        def do_POST(self) -> None:
            self._response_sent = False
            parsed = urlparse(self.path)

            if parsed.path == "/api/auth/register":
                payload = self._read_json_body()
                if payload is None:
                    return
                errors = validate_user_auth(payload, with_name=True)
                if errors:
                    self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                    return
                if app.storage.get_user_by_email(str(payload["email"]).strip().lower()):
                    self._send_json({"ok": False, "message": "Пользователь с такой почтой уже существует."}, status=HTTPStatus.CONFLICT)
                    return
                user, token = app.auth.register(payload)
                self._send_json(
                    {"ok": True, "user": user},
                    status=HTTPStatus.CREATED,
                    headers={"Set-Cookie": self._build_session_cookie(token)},
                )
                return

            if parsed.path == "/api/auth/login":
                payload = self._read_json_body()
                if payload is None:
                    return
                client_key = self._client_rate_key(str(payload.get("email", "")).strip().lower())
                allowed, retry_after = app.storage.consume_rate_limit(
                    "login",
                    client_key,
                    app.settings.login_rate_limit_count,
                    app.settings.login_rate_limit_window_seconds,
                )
                if not allowed:
                    self._send_json(
                        {"ok": False, "message": "Слишком много попыток входа. Попробуйте позже."},
                        status=HTTPStatus.TOO_MANY_REQUESTS,
                        headers={"Retry-After": str(retry_after)},
                    )
                    return
                errors = validate_user_auth(payload, with_name=False)
                if errors:
                    self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                    return
                result = app.auth.login(payload)
                if result is None:
                    self._send_json({"ok": False, "message": "Неверная почта или пароль."}, status=HTTPStatus.UNAUTHORIZED)
                    return
                user, token = result
                self._send_json(
                    {"ok": True, "user": user},
                    headers={"Set-Cookie": self._build_session_cookie(token)},
                )
                return

            if parsed.path == "/api/auth/password-reset/request":
                payload = self._read_json_body()
                if payload is None:
                    return
                email = str(payload.get("email", "")).strip().lower()
                allowed, retry_after = app.storage.consume_rate_limit(
                    "reset_request",
                    self._client_rate_key(email),
                    app.settings.reset_request_rate_limit_count,
                    app.settings.reset_request_rate_limit_window_seconds,
                )
                if not allowed:
                    self._send_json(
                        {"ok": False, "message": "Слишком много запросов на восстановление. Попробуйте позже."},
                        status=HTTPStatus.TOO_MANY_REQUESTS,
                        headers={"Retry-After": str(retry_after)},
                    )
                    return
                if "@" not in email or "." not in email:
                    self._send_json({"ok": False, "message": "Укажите корректную почту."}, status=HTTPStatus.BAD_REQUEST)
                    return
                user = app.storage.get_user_by_email(email)
                if user is None:
                    self._send_json({"ok": True, "message": "Если почта зарегистрирована, код будет отправлен."})
                    return
                try:
                    app.auth.request_password_reset(email)
                except Exception as error:
                    self._send_json({"ok": False, "message": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self._send_json({"ok": True, "message": "Код отправлен на электронную почту."})
                return

            if parsed.path == "/api/auth/password-reset/confirm":
                payload = self._read_json_body()
                if payload is None:
                    return
                email = str(payload.get("email", "")).strip().lower()
                code = str(payload.get("code", "")).strip()
                password = str(payload.get("password", ""))
                allowed, retry_after = app.storage.consume_rate_limit(
                    "reset_confirm",
                    self._client_rate_key(email),
                    app.settings.reset_confirm_rate_limit_count,
                    app.settings.reset_confirm_rate_limit_window_seconds,
                )
                if not allowed:
                    self._send_json(
                        {"ok": False, "message": "Слишком много попыток подтверждения. Попробуйте позже."},
                        status=HTTPStatus.TOO_MANY_REQUESTS,
                        headers={"Retry-After": str(retry_after)},
                    )
                    return
                if len(password) < 6:
                    self._send_json({"ok": False, "message": "Пароль должен содержать минимум 6 символов."}, status=HTTPStatus.BAD_REQUEST)
                    return
                if not app.auth.confirm_password_reset(email, code, password):
                    self._send_json({"ok": False, "message": "Неверный или просроченный код восстановления."}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True, "message": "Пароль обновлён. Теперь можно войти."})
                return

            if parsed.path == "/api/auth/logout":
                app.auth.logout(self._get_session_token())
                self._send_json({"ok": True}, headers={"Set-Cookie": self._build_clear_cookie()})
                return

            if parsed.path == "/api/chat/messages":
                user = self._require_user()
                if self._response_sent or user is None:
                    return
                payload = self._read_json_body()
                if payload is None:
                    return
                text = str(payload.get("text", "")).strip()
                attachment = payload.get("attachment")
                if len(text) < 1 and not attachment:
                    self._send_json({"ok": False, "message": "Сообщение не может быть пустым."}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    message = app.chat.create_message(int(user["id"]), "user", text, attachment)
                except Exception as error:
                    self._send_json({"ok": False, "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True, "item": message}, status=HTTPStatus.CREATED)
                return

            if parsed.path.startswith("/api/admin/chats/") and parsed.path.endswith("/messages"):
                self._require_admin()
                if self._response_sent:
                    return
                user_id_raw = parsed.path.removeprefix("/api/admin/chats/").removesuffix("/messages").strip("/")
                if not user_id_raw.isdigit():
                    self._send_json({"ok": False, "message": "Некорректный идентификатор пользователя."}, status=HTTPStatus.BAD_REQUEST)
                    return
                payload = self._read_json_body()
                if payload is None:
                    return
                text = str(payload.get("text", "")).strip()
                attachment = payload.get("attachment")
                if len(text) < 1 and not attachment:
                    self._send_json({"ok": False, "message": "Сообщение не может быть пустым."}, status=HTTPStatus.BAD_REQUEST)
                    return
                if app.storage.get_user_by_id(int(user_id_raw)) is None:
                    self._send_json({"ok": False, "message": "Пользователь не найден."}, status=HTTPStatus.NOT_FOUND)
                    return
                try:
                    message = app.chat.create_message(int(user_id_raw), "admin", text, attachment)
                except Exception as error:
                    self._send_json({"ok": False, "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True, "item": message}, status=HTTPStatus.CREATED)
                return

            if parsed.path == "/api/requests":
                payload = self._read_json_body()
                if payload is None:
                    return
                errors = self._validate_request(payload)
                if errors:
                    self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                    return
                auth_result = self._resolve_request_user(payload)
                if auth_result is None:
                    return
                user, token = auth_result
                attachment_payload = payload.pop("attachment", None)
                attachment = None
                if isinstance(attachment_payload, dict) and attachment_payload.get("contentBase64"):
                    try:
                        attachment = app.chat.store_attachment(attachment_payload)
                    except Exception as error:
                        self._send_json({"ok": False, "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
                        return
                payload["userId"] = user["id"]
                if attachment:
                    payload["attachment"] = attachment
                record = app.reviews.save_request(payload)
                app.storage.create_message(int(user["id"]), "user", self._format_request_message(record), attachment)
                headers = {"Set-Cookie": self._build_session_cookie(token)} if token else None
                self._send_json(
                    {
                        "ok": True,
                        "message": "Заявка отправлена. Дальнейший диалог будет идти в чате с администратором.",
                        "requestId": record["id"],
                        "redirectTo": "/chat",
                    },
                    status=HTTPStatus.CREATED,
                    headers=headers,
                )
                return

            if parsed.path == "/api/reviews":
                payload = self._read_json_body()
                if payload is None:
                    return
                errors = self._validate_review(payload)
                if errors:
                    self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                    return
                record = app.reviews.save_review(payload)
                self._send_json(
                    {"ok": True, "message": "Отзыв отправлен и отобразится в течении нескольких минут.", "reviewId": record["id"]},
                    status=HTTPStatus.CREATED,
                )
                return

            if parsed.path.startswith("/api/admin/reviews/") and parsed.path.endswith("/approve"):
                self._change_review_status(parsed.path, "approved")
                return

            if parsed.path.startswith("/api/admin/reviews/") and parsed.path.endswith("/reject"):
                self._change_review_status(parsed.path, "rejected")
                return

            if parsed.path == "/api/admin/works":
                self._require_admin()
                if self._response_sent:
                    return
                payload = self._read_json_body()
                if payload is None:
                    return
                errors = self._validate_work(payload)
                if errors:
                    self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                    return
                attachment_payload = payload.pop("attachment", None)
                if isinstance(attachment_payload, dict) and attachment_payload.get("contentBase64"):
                    try:
                        payload["attachment"] = app.chat.store_attachment(attachment_payload)
                    except Exception as error:
                        self._send_json({"ok": False, "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
                        return
                record = app.reviews.save_work(payload)
                self._send_json({"ok": True, "message": f"Работа #{record['id']} добавлена.", "item": record}, status=HTTPStatus.CREATED)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

        def do_DELETE(self) -> None:
            self._response_sent = False
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/admin/works/"):
                self._require_admin()
                if self._response_sent:
                    return
                work_id_raw = parsed.path.removeprefix("/api/admin/works/").strip("/")
                if not work_id_raw.isdigit():
                    self._send_json({"ok": False, "message": "Некорректный идентификатор работы."}, status=HTTPStatus.BAD_REQUEST)
                    return
                deleted = app.reviews.delete_work(int(work_id_raw))
                if deleted is None:
                    self._send_json({"ok": False, "message": "Работа не найдена."}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "message": f"Работа #{work_id_raw} удалена."})
                return

            if parsed.path.startswith("/api/admin/reviews/"):
                self._require_admin()
                if self._response_sent:
                    return
                review_id_raw = parsed.path.removeprefix("/api/admin/reviews/").strip("/")
                if not review_id_raw.isdigit():
                    self._send_json({"ok": False, "message": "Некорректный идентификатор отзыва."}, status=HTTPStatus.BAD_REQUEST)
                    return
                deleted = app.reviews.delete_review(int(review_id_raw))
                if deleted is None:
                    self._send_json({"ok": False, "message": "Отзыв не найден."}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "message": f"Отзыв #{review_id_raw} удалён."})
                return

            if not parsed.path.startswith("/api/requests/"):
                self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")
                return

            self._require_admin()
            if self._response_sent:
                return
            request_id_raw = parsed.path.removeprefix("/api/requests/").strip("/")
            if not request_id_raw.isdigit():
                self._send_json({"ok": False, "message": "Некорректный идентификатор заявки."}, status=HTTPStatus.BAD_REQUEST)
                return
            deleted = app.reviews.delete_request(int(request_id_raw))
            if deleted is None:
                self._send_json({"ok": False, "message": "Заявка не найдена."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, "message": f"Заявка #{request_id_raw} удалена."})

        def do_PUT(self) -> None:
            self._response_sent = False
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/admin/works/"):
                self._require_admin()
                if self._response_sent:
                    return
                work_id_raw = parsed.path.removeprefix("/api/admin/works/").strip("/")
                if not work_id_raw.isdigit():
                    self._send_json({"ok": False, "message": "Некорректный идентификатор работы."}, status=HTTPStatus.BAD_REQUEST)
                    return
                payload = self._read_json_body()
                if payload is None:
                    return
                errors = self._validate_work(payload)
                if errors:
                    self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                    return
                attachment_payload = payload.pop("attachment", None)
                if isinstance(attachment_payload, dict) and attachment_payload.get("contentBase64"):
                    try:
                        payload["attachment"] = app.chat.store_attachment(attachment_payload)
                    except Exception as error:
                        self._send_json({"ok": False, "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
                        return
                updated = app.reviews.update_work(int(work_id_raw), payload)
                if updated is None:
                    self._send_json({"ok": False, "message": "Работа не найдена."}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "message": f"Работа #{work_id_raw} сохранена.", "item": updated})
                return

            if not parsed.path.startswith("/api/admin/reviews/"):
                self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")
                return
            self._require_admin()
            if self._response_sent:
                return
            review_id_raw = parsed.path.removeprefix("/api/admin/reviews/").strip("/")
            if not review_id_raw.isdigit():
                self._send_json({"ok": False, "message": "Некорректный идентификатор отзыва."}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = self._read_json_body()
            if payload is None:
                return
            errors = self._validate_review(payload)
            if errors:
                self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                return
            updated = app.reviews.update_review(int(review_id_raw), payload)
            if updated is None:
                self._send_json({"ok": False, "message": "Отзыв не найден."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, "message": f"Отзыв #{review_id_raw} сохранён.", "item": updated})

        @property
        def _response_sent(self) -> bool:
            return getattr(self, "__response_sent", False)

        @_response_sent.setter
        def _response_sent(self, value: bool) -> None:
            self.__response_sent = value

        def _read_json_body(self) -> dict | None:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > app.settings.max_request_size:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid request size")
                self._response_sent = True
                return None
            try:
                raw_body = self.rfile.read(content_length)
                payload = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON payload")
                self._response_sent = True
                return None
            if not isinstance(payload, dict):
                self._send_json({"ok": False, "message": "Ожидался JSON-объект."}, status=HTTPStatus.BAD_REQUEST)
                return None
            return payload

        def _get_session_token(self) -> str:
            raw_cookie = self.headers.get("Cookie", "")
            if not raw_cookie:
                return ""
            cookie = SimpleCookie()
            cookie.load(raw_cookie)
            morsel = cookie.get(app.settings.session_cookie_name)
            return morsel.value if morsel else ""

        def _require_user(self) -> dict | None:
            token = self._get_session_token()
            if not token:
                self._send_json({"ok": False, "message": "Требуется авторизация пользователя."}, status=HTTPStatus.UNAUTHORIZED)
                return None
            user = app.auth.get_user_by_session(token)
            if user is None:
                self._send_json(
                    {"ok": False, "message": "Сессия пользователя не найдена."},
                    status=HTTPStatus.UNAUTHORIZED,
                    headers={"Set-Cookie": self._build_clear_cookie()},
                )
                return None
            return user

        def _require_admin(self) -> None:
            if is_admin_authorized(self.headers.get("Authorization", ""), app.settings):
                return
            body = json.dumps(
                {"ok": False, "message": "Требуется авторизация для доступа к админ-панели."},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("WWW-Authenticate", 'Basic realm="Admin Panel"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self._response_sent = True

        def _build_session_cookie(self, token: str) -> str:
            return (
                f"{app.settings.session_cookie_name}={token}; "
                f"HttpOnly; Path=/; SameSite=Lax; Max-Age={app.settings.session_ttl_seconds}"
            )

        def _build_clear_cookie(self) -> str:
            return (
                f"{app.settings.session_cookie_name}=; "
                "HttpOnly; Path=/; SameSite=Lax; Max-Age=0"
            )

        def _client_rate_key(self, suffix: str = "") -> str:
            base = self.client_address[0]
            return f"{base}:{suffix}" if suffix else base

        def _change_review_status(self, path: str, status: str) -> None:
            self._require_admin()
            if self._response_sent:
                return
            review_id_raw = path.removeprefix("/api/admin/reviews/").removesuffix("/approve").removesuffix("/reject").strip("/")
            if not review_id_raw.isdigit():
                self._send_json({"ok": False, "message": "Некорректный идентификатор отзыва."}, status=HTTPStatus.BAD_REQUEST)
                return
            updated = app.reviews.update_review_status(int(review_id_raw), status)
            if updated is None:
                self._send_json({"ok": False, "message": "Отзыв не найден."}, status=HTTPStatus.NOT_FOUND)
                return
            verb = "одобрен" if status == "approved" else "отклонён"
            self._send_json({"ok": True, "message": f"Отзыв #{review_id_raw} {verb}."})

        def _resolve_request_user(self, payload: dict) -> tuple[dict, str] | None:
            current_user = app.auth.get_user_by_session(self._get_session_token())
            if current_user is not None:
                return current_user, ""
            auth_payload = {
                "name": str(payload.get("name", "")).strip(),
                "email": str(payload.get("authEmail", "")).strip().lower(),
                "password": str(payload.get("authPassword", "")),
            }
            errors = validate_user_auth(auth_payload, with_name=True)
            if errors:
                self._send_json(
                    {"ok": False, "errors": errors, "message": "Для отправки заявки нужно создать аккаунт или войти."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return None
            existing_user = app.storage.get_user_by_email(auth_payload["email"])
            if existing_user is None:
                return app.auth.register(auth_payload)
            login_result = app.auth.login(auth_payload)
            if login_result is None:
                self._send_json(
                    {"ok": False, "message": "Почта уже зарегистрирована. Введите пароль от аккаунта или используйте другую почту."},
                    status=HTTPStatus.CONFLICT,
                )
                return None
            return login_result

        def _format_request_message(self, record: dict) -> str:
            lines = [
                f"Новая заявка #{record.get('id')}",
                f"Имя: {record.get('name', '')}",
                f"Контакт: {record.get('contact', '')}",
                f"Тип работы: {record.get('taskType', '')}",
                f"Антиплагиат: {record.get('antiPlagiarism', '')}",
                f"Дедлайн: {record.get('deadline', '')}",
                "",
                "Описание:",
                str(record.get("details", "")),
            ]
            return "\n".join(lines).strip()

        def _serve_static(self, raw_path: str) -> None:
            routes = {
                "/": "/index.html",
                "/chat": "/chat.html",
                "/admin": "/admin.html",
                "/admin/chats": "/admin-chats.html",
            }
            requested = routes.get(raw_path.rstrip("/") or "/", raw_path.rstrip("/") or "/index.html")
            if raw_path.startswith("/uploads/"):
                relative_upload_path = raw_path.removeprefix("/uploads/").lstrip("/")
                file_path = (app.settings.uploads_dir / relative_upload_path).resolve()
                allowed_root = app.settings.uploads_dir
            else:
                file_path = (app.settings.static_dir / requested.lstrip("/")).resolve()
                allowed_root = app.settings.static_dir
            if allowed_root not in file_path.parents and file_path != allowed_root:
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                self._response_sent = True
                return
            if not file_path.exists() or not file_path.is_file():
                if raw_path.startswith("/uploads/"):
                    self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                    self._response_sent = True
                    return
                file_path = app.settings.static_dir / "index.html"
            try:
                content = file_path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to read file")
                self._response_sent = True
                return
            content_type, _ = mimetypes.guess_type(str(file_path))
            resolved_content_type = content_type or "application/octet-stream"
            if resolved_content_type.startswith("text/") or resolved_content_type in {"application/javascript", "application/json", "image/svg+xml"}:
                resolved_content_type = f"{resolved_content_type}; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", resolved_content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            self._response_sent = True

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if headers:
                for key, value in headers.items():
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self._response_sent = True

        def _validate_request(self, payload: dict) -> dict[str, str]:
            required_fields = {
                "name": "Укажите имя.",
                "contact": "Укажите способ связи.",
                "taskType": "Выберите тип работы.",
                "antiPlagiarism": "Выберите тип антиплагиата.",
                "deadline": "Укажите срок.",
                "details": "Опишите задачу.",
            }
            errors: dict[str, str] = {}
            for field, message in required_fields.items():
                value = payload.get(field, "")
                if not isinstance(value, str) or not value.strip():
                    errors[field] = message
            details = str(payload.get("details", ""))
            if details and len(details.strip()) < 20:
                errors["details"] = "Опишите задачу чуть подробнее, минимум 20 символов."
            return errors

        def _validate_work(self, payload: dict) -> dict[str, str]:
            required_fields = {
                "title": "Укажите название работы.",
                "workType": "Укажите тип работы.",
                "subject": "Укажите предмет или направление.",
                "description": "Добавьте краткое описание.",
            }
            errors: dict[str, str] = {}
            for field, message in required_fields.items():
                value = payload.get(field, "")
                if not isinstance(value, str) or not value.strip():
                    errors[field] = message
            description = str(payload.get("description", ""))
            if description and len(description.strip()) < 20:
                errors["description"] = "Описание должно быть подробнее, минимум 20 символов."
            return errors

        def _validate_review(self, payload: dict) -> dict[str, str]:
            required_fields = {
                "name": "Укажите имя.",
                "role": "Укажите, кто вы или на каком направлении учитесь.",
                "text": "Напишите отзыв.",
            }
            errors: dict[str, str] = {}
            for field, message in required_fields.items():
                value = payload.get(field, "")
                if not isinstance(value, str) or not value.strip():
                    errors[field] = message
            text = str(payload.get("text", ""))
            if text and len(text.strip()) < 30:
                errors["text"] = "Отзыв должен быть чуть подробнее, минимум 30 символов."
            return errors

        def log_message(self, format: str, *args: object) -> None:
            return

    return AppHandler


def create_server(settings: Settings | None = None, host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    effective_settings = settings or Settings.from_env(ROOT_DIR)
    app = Application(effective_settings)
    app.initialize()
    bind_host = host or "0.0.0.0"
    bind_port = port if port is not None else int(os.getenv("PORT", "8000"))
    return ThreadingHTTPServer((bind_host, bind_port), create_handler(app))


def run() -> None:
    settings = Settings.from_env(ROOT_DIR)
    app = Application(settings)
    app.initialize()
    host = "0.0.0.0"
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), create_handler(app))
    print(f"Server running on http://{host}:{port}")
    print(f"Admin panel: http://{host}:{port}/admin")
    print("Set ADMIN_USERNAME and ADMIN_PASSWORD to change admin credentials.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
