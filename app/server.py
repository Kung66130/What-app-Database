from __future__ import annotations

import json
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import settings
from .services import (
    ask_agent,
    database_status,
    export_state,
    handle_evolution_webhook,
    handle_slack_command,
    import_export_content,
    list_groups,
    list_import_batches,
    list_users,
    search_messages,
    system_status,
    verify_slack_signature,
)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "WhatsAppAgentMVP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        query = parse_qs(parsed.query)

        if path == "/health":
            self._write_json({"status": "ok", "app": settings.app_name})
            return

        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT.value)
            self.end_headers()
            return

        if path in {"/", "/dashboard"}:
            self._write_html(DASHBOARD_HTML)
            return

        if not self._authorize_api_request():
            return

        if path == "/groups":
            self._write_json({"groups": list_groups()})
            return

        if path == "/users":
            limit = int(query.get("limit", ["100"])[0])
            self._write_json({"users": list_users(limit=limit)})
            return

        if path == "/imports":
            limit = int(query.get("limit", ["20"])[0])
            self._write_json({"imports": list_import_batches(limit=limit)})
            return

        if path == "/db/status":
            self._write_json({"database": database_status()})
            return

        if path == "/system/status":
            self._write_json({"system": system_status()})
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
        path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        print(f"DEBUG: Incoming POST request to {path}")

        # Slack sends form-urlencoded data for commands, NOT JSON
        if path == "/slack/command":
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            
            timestamp = self.headers.get("X-Slack-Request-Timestamp", "")
            signature = self.headers.get("X-Slack-Signature", "")
            
            # 1. Acknowledge immediately to avoid timeout
            self._write_json({"response_type": "ephemeral", "text": "⏳ กำลังประมวลผลคำสั่งของคุณ..."}, status=HTTPStatus.OK)

            # 2. Process in background
            import threading
            def bg_work(body, ts, sig):
                if not verify_slack_signature(ts, sig, body):
                    print(f"Unauthorized Slack request")
                    return
                
                params = parse_qs(body.decode("utf-8"))
                text = params.get("text", [""])[0]
                channel_id = params.get("channel_id", [""])[0]
                response_url = params.get("response_url", [None])[0]
                
                print(f"Slack command (BG): {text} in {channel_id}")
                handle_slack_command(text, channel_id=channel_id, response_url=response_url)

            threading.Thread(target=bg_work, args=(raw_body, timestamp, signature)).start()
            return

        # --- Slack Events API ---
        if path == "/slack/events":
            body = self._read_json_body()
            if not body: return
            
            # 1. URL Verification
            if body.get("type") == "url_verification":
                self._write_json({"challenge": body.get("challenge")})
                return
            
            # 2. Event Callback
            if body.get("type") == "event_callback":
                event = body.get("event", {})
                event_type = event.get("type")
                
                # Check if it's a message in a channel we care about
                if event_type == "message" and not event.get("bot_id"):
                    channel_id = event.get("channel")
                    text = event.get("text", "")
                    
                    allowed_channels = [c.strip() for c in settings.slack_allowed_channels.split(",") if c.strip()]
                    if channel_id in allowed_channels:
                        print(f"DEBUG: Slack message from {channel_id}: {text}")
                        
                        # Forward to WhatsApp group "Wax Team Chat"
                        def forward_to_wa():
                            from .services import get_connection, send_to_whatsapp
                            conn = get_connection()
                            try:
                                group = conn.execute("SELECT remote_jid FROM groups WHERE group_name = 'Wax Team Chat' LIMIT 1").fetchone()
                                if group and group["remote_jid"]:
                                    send_to_whatsapp(text, group["remote_jid"])
                            finally:
                                conn.close()
                        
                        import threading
                        threading.Thread(target=forward_to_wa).start()

                self._write_json({"status": "ok"})
                return

        # All other POST endpoints expect JSON
        body = self._read_json_body()
        if body is None:
            print("DEBUG: Failed to read JSON body")
            return

        if path.startswith("/webhooks/whatsapp"):
            query = parse_qs(parsed.query)
            if not self._authorize_webhook_request(query):
                return
            print(f"DEBUG: Received WhatsApp Webhook on {path}: {json.dumps(body)[:100]}...")
            result = handle_evolution_webhook(body)
            self._write_json(result)
            return

        if not self._authorize_api_request():
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

    def _write_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorize_api_request(self) -> bool:
        if not settings.api_key:
            return True

        supplied = self.headers.get("X-WA-Agent-Key", "")
        if not supplied:
            auth_header = self.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                supplied = auth_header[7:].strip()

        if hmac.compare_digest(supplied, settings.api_key):
            return True

        self._write_json({"error": "Unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return False

    def _authorize_webhook_request(self, query: dict[str, list[str]] | None = None) -> bool:
        if not settings.webhook_secret:
            return True

        supplied = self.headers.get("X-WA-Webhook-Secret", "")
        if not supplied and query:
            supplied = _one(query, "secret", "") or ""
        if hmac.compare_digest(supplied, settings.webhook_secret):
            return True

        self._write_json({"error": "Unauthorized webhook"}, status=HTTPStatus.UNAUTHORIZED)
        return False


def run_server() -> None:
    server = ThreadingHTTPServer((settings.host, settings.port), ApiHandler)
    print(f"{settings.app_name} listening on http://{settings.host}:{settings.port}")
    server.serve_forever()


def _one(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[0]


DASHBOARD_HTML = r"""<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WhatsApp Agent Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f4;
      --surface: #ffffff;
      --surface-soft: #eef5f1;
      --text: #17211d;
      --muted: #61706a;
      --line: #dbe3df;
      --accent: #0b7f65;
      --accent-dark: #075d4a;
      --warn: #a86600;
      --danger: #b42318;
      --radius: 8px;
      --shadow: 0 14px 34px rgba(23, 33, 29, 0.08);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.45;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 18px 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.86);
      position: sticky;
      top: 0;
      z-index: 5;
      backdrop-filter: blur(12px);
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 760;
      letter-spacing: 0;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 15px;
      font-weight: 730;
      letter-spacing: 0;
    }
    .status {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      white-space: nowrap;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--warn);
    }
    .dot.ok { background: var(--accent); }
    main {
      width: min(1180px, calc(100vw - 28px));
      margin: 22px auto 40px;
      display: grid;
      gap: 16px;
    }
    .toolbar, section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .toolbar {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
      padding: 14px;
      align-items: center;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    section {
      padding: 16px;
      min-width: 0;
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 680;
      margin-bottom: 6px;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px 11px;
      color: var(--text);
      background: #fff;
      font: inherit;
      min-height: 40px;
    }
    textarea { min-height: 92px; resize: vertical; }
    button {
      border: 0;
      border-radius: 7px;
      background: var(--accent);
      color: #fff;
      min-height: 40px;
      padding: 0 14px;
      font-weight: 720;
      cursor: pointer;
    }
    button.secondary {
      background: var(--surface-soft);
      color: var(--accent-dark);
      border: 1px solid #cce1d8;
    }
    button:hover { filter: brightness(0.96); }
    .fields {
      display: grid;
      grid-template-columns: 1.3fr 1fr auto;
      gap: 10px;
      align-items: end;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
    }
    .metric {
      background: var(--surface-soft);
      border: 1px solid #d7e7df;
      border-radius: var(--radius);
      padding: 14px;
      min-height: 84px;
    }
    .metric strong {
      display: block;
      font-size: 28px;
      line-height: 1.1;
      margin-bottom: 8px;
    }
    .metric span { color: var(--muted); }
    .system-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }
    .system-item {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 11px;
      background: #fff;
      min-height: 72px;
    }
    .system-item strong {
      display: block;
      font-size: 17px;
      margin-top: 3px;
    }
    .system-item span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 680;
    }
    .list {
      display: grid;
      gap: 8px;
      max-height: 330px;
      overflow: auto;
      padding-right: 2px;
    }
    .row {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: #fff;
    }
    .row-top {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }
    .content { white-space: pre-wrap; word-break: break-word; }
    .answer {
      background: #f9fbfa;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 12px;
      min-height: 110px;
      white-space: pre-wrap;
    }
    .muted { color: var(--muted); }
    .error { color: var(--danger); }
    .stack { display: grid; gap: 10px; }
    @media (max-width: 820px) {
      header, .toolbar, .fields { grid-template-columns: 1fr; align-items: stretch; }
      header { display: grid; padding: 16px; }
      .grid, .summary, .system-grid { grid-template-columns: 1fr; }
      main { width: min(100vw - 20px, 1180px); margin-top: 12px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>WhatsApp Agent Dashboard</h1>
    <div class="status"><span id="healthDot" class="dot"></span><span id="healthText">checking</span></div>
  </header>
  <main>
    <div class="toolbar">
      <div>
        <label for="apiKey">API key</label>
        <input id="apiKey" type="password" autocomplete="off" placeholder="X-WA-Agent-Key">
      </div>
      <button id="saveKey" class="secondary" type="button">Save key</button>
      <button id="refresh" type="button">Refresh</button>
    </div>

    <section>
      <h2>Overview</h2>
      <div class="summary">
        <div class="metric"><strong id="groupCount">-</strong><span>groups</span></div>
        <div class="metric"><strong id="userCount">-</strong><span>users</span></div>
        <div class="metric"><strong id="importCount">-</strong><span>imports</span></div>
        <div class="metric"><strong id="messageCount">-</strong><span>messages</span></div>
      </div>
      <p id="dbStatus" class="muted" style="margin:12px 0 0">Database: checking</p>
    </section>

    <section>
      <h2>Pi Status</h2>
      <div class="system-grid">
        <div class="system-item"><span>Uptime</span><strong id="uptime">-</strong></div>
        <div class="system-item"><span>CPU load</span><strong id="loadAverage">-</strong></div>
        <div class="system-item"><span>CPU temp</span><strong id="temperature">-</strong></div>
        <div class="system-item"><span>Memory</span><strong id="memory">-</strong></div>
        <div class="system-item"><span>Data disk</span><strong id="dataDisk">-</strong></div>
        <div class="system-item"><span>Evolution API</span><strong id="evolutionStatus">-</strong></div>
      </div>
      <p id="systemDetail" class="muted" style="margin:12px 0 0">System: checking</p>
    </section>

    <div class="grid">
      <section>
        <h2>Search Messages</h2>
        <div class="fields">
          <div>
            <label for="searchText">Query</label>
            <input id="searchText" placeholder="SKU-001, shipment, delay">
          </div>
          <div>
            <label for="groupName">Group</label>
            <input id="groupName" placeholder="UK Team">
          </div>
          <button id="runSearch" type="button">Search</button>
        </div>
        <div id="messages" class="list" style="margin-top:12px"></div>
      </section>

      <section>
        <h2>Ask Agent</h2>
        <div class="stack">
          <textarea id="question" placeholder="ใครสั่งสินค้า SKU-001 ครั้งล่าสุด"></textarea>
          <button id="runAsk" type="button">Ask</button>
          <div id="answer" class="answer muted">No answer yet</div>
        </div>
      </section>
    </div>

    <div class="grid">
      <section>
        <h2>Recent Imports</h2>
        <div id="imports" class="list"></div>
      </section>
      <section>
        <h2>Users</h2>
        <div id="users" class="list"></div>
      </section>
    </div>
  </main>

  <script>
    const els = {
      apiKey: document.getElementById('apiKey'),
      healthDot: document.getElementById('healthDot'),
      healthText: document.getElementById('healthText'),
      groupCount: document.getElementById('groupCount'),
      userCount: document.getElementById('userCount'),
      importCount: document.getElementById('importCount'),
      messageCount: document.getElementById('messageCount'),
      dbStatus: document.getElementById('dbStatus'),
      uptime: document.getElementById('uptime'),
      loadAverage: document.getElementById('loadAverage'),
      temperature: document.getElementById('temperature'),
      memory: document.getElementById('memory'),
      dataDisk: document.getElementById('dataDisk'),
      evolutionStatus: document.getElementById('evolutionStatus'),
      systemDetail: document.getElementById('systemDetail'),
      messages: document.getElementById('messages'),
      imports: document.getElementById('imports'),
      users: document.getElementById('users'),
      searchText: document.getElementById('searchText'),
      groupName: document.getElementById('groupName'),
      question: document.getElementById('question'),
      answer: document.getElementById('answer'),
    };

    els.apiKey.value = localStorage.getItem('waAgentApiKey') || '';
    document.getElementById('saveKey').addEventListener('click', () => {
      localStorage.setItem('waAgentApiKey', els.apiKey.value.trim());
      refreshAll();
    });
    document.getElementById('refresh').addEventListener('click', refreshAll);
    document.getElementById('runSearch').addEventListener('click', runSearch);
    document.getElementById('runAsk').addEventListener('click', runAsk);

    function headers(extra = {}) {
      const key = els.apiKey.value.trim();
      return key ? {...extra, 'X-WA-Agent-Key': key} : extra;
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {...options, headers: headers(options.headers || {})});
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }

    function row(topLeft, topRight, content) {
      return `<div class="row"><div class="row-top"><span>${escapeHtml(topLeft)}</span><span>${escapeHtml(topRight || '')}</span></div><div class="content">${escapeHtml(content || '')}</div></div>`;
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }

    async function checkHealth() {
      try {
        const data = await api('/health');
        els.healthDot.classList.add('ok');
        els.healthText.textContent = data.status;
      } catch (err) {
        els.healthDot.classList.remove('ok');
        els.healthText.textContent = 'offline';
      }
    }

    async function refreshAll() {
      await checkHealth();
      try {
        const [groups, users, imports, system] = await Promise.all([
          api('/groups'),
          api('/users?limit=20'),
          api('/imports?limit=20'),
          api('/system/status'),
        ]);
        const db = await api('/db/status');
        const counts = db.database.counts || {};
        els.groupCount.textContent = counts.groups ?? groups.groups.length;
        els.userCount.textContent = counts.users ?? users.users.length;
        els.importCount.textContent = counts.import_batches ?? imports.imports.length;
        els.messageCount.textContent = counts.messages ?? '-';
        els.dbStatus.textContent = `Database: ${db.database.db_path}`;
        renderSystem(system.system);
        els.users.innerHTML = users.users.map(u => row(u.display_name, `${u.msg_count} messages`, u.normalized_name)).join('') || '<p class="muted">No users</p>';
        els.imports.innerHTML = imports.imports.map(i => row(i.group_name, i.imported_at, `${i.file_name} | new ${i.new_messages} | duplicate ${i.duplicate_messages}`)).join('') || '<p class="muted">No imports</p>';
      } catch (err) {
        els.imports.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
        els.users.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
      }
    }

    function renderSystem(system) {
      const memory = system.memory;
      const dataDisk = system.disk && system.disk.data_dir;
      const load = system.load_average || [];
      els.uptime.textContent = formatDuration(system.uptime_seconds);
      els.loadAverage.textContent = load.length ? load.map(n => Number(n).toFixed(2)).join(' / ') : '-';
      els.temperature.textContent = system.temperature_c == null ? 'n/a' : `${system.temperature_c} C`;
      els.memory.textContent = memory ? `${memory.used_percent}% used` : 'n/a';
      els.dataDisk.textContent = dataDisk ? `${dataDisk.used_percent}% used` : 'n/a';
      els.evolutionStatus.textContent = system.integrations && system.integrations.evolution_reachable ? 'reachable' : 'not reachable';
      els.systemDetail.textContent = `Host: ${system.hostname} | Python ${system.python_version} | data ${system.app.data_dir}`;
    }

    function formatDuration(seconds) {
      if (seconds == null) return 'n/a';
      const value = Number(seconds);
      const days = Math.floor(value / 86400);
      const hours = Math.floor((value % 86400) / 3600);
      const minutes = Math.floor((value % 3600) / 60);
      if (days > 0) return `${days}d ${hours}h`;
      if (hours > 0) return `${hours}h ${minutes}m`;
      return `${minutes}m`;
    }

    async function runSearch() {
      const params = new URLSearchParams();
      if (els.searchText.value.trim()) params.set('q', els.searchText.value.trim());
      if (els.groupName.value.trim()) params.set('group_name', els.groupName.value.trim());
      params.set('limit', '20');
      try {
        const data = await api(`/messages/search?${params.toString()}`);
        els.messages.innerHTML = data.messages.map(m => row(m.sender_name || 'System', m.sent_at, m.content_raw)).join('') || '<p class="muted">No messages</p>';
      } catch (err) {
        els.messages.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
      }
    }

    async function runAsk() {
      const question = els.question.value.trim();
      if (!question) return;
      els.answer.textContent = 'Thinking...';
      try {
        const data = await api('/agent/ask', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({question, group_name: els.groupName.value.trim() || undefined, limit: 8}),
        });
        const cites = (data.citations || []).map(c => `- ${c.sent_at} | ${c.sender}: ${c.content_raw}`).join('\n');
        els.answer.classList.remove('muted');
        els.answer.textContent = `${data.answer}\n\nCitations:\n${cites || '-'}`;
      } catch (err) {
        els.answer.classList.add('error');
        els.answer.textContent = err.message;
      }
    }

    refreshAll();
  </script>
</body>
</html>"""
