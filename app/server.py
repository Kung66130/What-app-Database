from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import settings
from .services import ask_agent, export_state, import_export_content, list_groups, list_import_batches, search_messages


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "WhatsAppAgentMVP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            self._write_json({"status": "ok", "app": settings.app_name})
            return

        if path == "/groups":
            self._write_json({"groups": list_groups()})
            return

        if path == "/imports":
            limit = int(query.get("limit", ["20"])[0])
            self._write_json({"imports": list_import_batches(limit=limit)})
            return

        if path == "/messages/search":
            rows = search_messages(
                q=_one(query, "q"),
                group_name=_one(query, "group_name"),
                sender=_one(query, "sender"),
                date_from=_one(query, "date_from"),
                date_to=_one(query, "date_to"),
                limit=int(_one(query, "limit", "20")),
            )
            self._write_json({"messages": rows, "count": len(rows)})
            return

        self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()
        if body is None:
            return

        if path == "/imports/whatsapp":
            required = ["group_name", "file_name", "content"]
            missing = [name for name in required if not body.get(name)]
            if missing:
                self._write_json({"error": f"Missing fields: {', '.join(missing)}"}, status=HTTPStatus.BAD_REQUEST)
                return
            result = import_export_content(
                group_name=body["group_name"],
                file_name=body["file_name"],
                content=body["content"],
                source_owner=body.get("source_owner"),
            )
            self._write_json({"import_result": result.__dict__}, status=HTTPStatus.CREATED)
            return

        if path == "/agent/ask":
            question = body.get("question", "").strip()
            if not question:
                self._write_json({"error": "Missing field: question"}, status=HTTPStatus.BAD_REQUEST)
                return
            result = ask_agent(
                question=question,
                group_name=body.get("group_name"),
                sender=body.get("sender"),
                date_from=body.get("date_from"),
                date_to=body.get("date_to"),
                limit=int(body.get("limit", 8)),
            )
            self._write_json(result)
            return

        if path == "/debug/state":
            self._write_json(export_state())
            return

        self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json_body(self) -> dict | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length else b"{}"
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._write_json({"error": "Body must be valid JSON"}, status=HTTPStatus.BAD_REQUEST)
            return None

    def _write_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server() -> None:
    server = ThreadingHTTPServer((settings.host, settings.port), ApiHandler)
    print(f"{settings.app_name} listening on http://{settings.host}:{settings.port}")
    server.serve_forever()


def _one(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[0]
