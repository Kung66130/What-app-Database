from __future__ import annotations

import hashlib
import http.client
import os
import platform
import shutil
import socket
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any
import json
import urllib.request
import urllib.error
import urllib.parse
import hmac
import hashlib
import threading
import base64
import time

from .config import settings
from .db import get_connection, init_db, utc_now_iso
from .parser import ParsedMessage, normalize_name, parse_whatsapp_export


def handle_evolution_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Handles incoming message events from Evolution API."""
    event = payload.get("event")
    if event != "messages.upsert":
        return {"status": "ignored", "event": event}

    data = payload.get("data", {})
    key = data.get("key", {})
    message = data.get("message", {})

    remote_jid = str(key.get("remoteJid") or "")
    message_id = str(key.get("id") or "")
    if not remote_jid:
        return {"status": "ignored", "reason": "missing_remote_jid"}

    is_group = "@g.us" in remote_jid
    sender_name = _extract_sender_name(data, key, remote_jid)
    content, message_type = _extract_message_content(message)

    if not content:
        return {"status": "ignored", "reason": "empty_content"}

    group_name = _extract_group_name(data, remote_jid, is_group)

    media_path = None
    if "imageMessage" in message:
        media_path = _save_evolution_media(data.get("base64"), message_id or "image", "jpg")

    conn = get_connection()
    try:
        now_iso = utc_now_iso()

        conn.execute(
            """
            INSERT INTO groups (group_name, remote_jid, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(group_name) DO UPDATE SET
                remote_jid=excluded.remote_jid
            """,
            (group_name, remote_jid, now_iso),
        )
        group_id = conn.execute("SELECT id FROM groups WHERE group_name = ?", (group_name,)).fetchone()["id"]

        normalized_name = normalize_name(sender_name)
        conn.execute(
            """
            INSERT INTO users (display_name, normalized_name, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET
                display_name=excluded.display_name
            """,
            (sender_name, normalized_name, now_iso),
        )
        sender_id = conn.execute("SELECT id FROM users WHERE normalized_name = ?", (normalized_name,)).fetchone()["id"]

        batch_id = _get_or_create_live_batch(conn, group_id, now_iso)

        timestamp = _evolution_timestamp_to_iso(data.get("messageTimestamp"))
        source_hash = _evolution_source_hash(remote_jid, message_id, timestamp, content)

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO messages (group_id, sender_id, batch_id, sent_at, message_type, content_raw, content_normalized, media_path, source_hash, source_line_start, source_line_end, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (group_id, sender_id, batch_id, timestamp, message_type, content, content.lower(), media_path, source_hash, now_iso),
        )
        is_new = cursor.rowcount == 1
        conn.execute(
            """
            UPDATE import_batches
            SET
                parsed_messages = parsed_messages + 1,
                new_messages = new_messages + ?,
                duplicate_messages = duplicate_messages + ?
            WHERE id = ?
            """,
            (1 if is_new else 0, 0 if is_new else 1, batch_id),
        )
        conn.commit()

        # --- Automated Translation and Slack Notification for "Wax Team Chat" ---
        # Also handle "Wax Team Chat" (case-insensitive or exact)
        if group_name.lower().strip() == "wax team chat" and content and not content.startswith("["):
            def process_and_notify():
                try:
                    # 1. Translate using Gemini
                    thai_text = translate_to_thai(content)
                    
                    # 2. Prepare Slack Message
                    slack_msg = f"📩 *{sender_name}* in *{group_name}*:\n{content}\n\n*แปลไทย:* {thai_text}"
                    
                    # 3. Send to Slack (using the first allowed channel)
                    target_channel = settings.slack_allowed_channels.split(",")[0].strip()
                    if target_channel:
                        send_to_slack(slack_msg, target_channel)
                        print(f"DEBUG: Sent translated message to Slack {target_channel}")
                except Exception as e:
                    print(f"DEBUG: Translation/Slack Notification failed: {e}")

            threading.Thread(target=process_and_notify).start()

        return {
            "status": "success",
            "message_id": message_id,
            "new_message": is_new,
            "group_name": group_name,
            "sender_name": sender_name,
        }
    finally:
        conn.close()


def _extract_sender_name(data: dict[str, Any], key: dict[str, Any], remote_jid: str) -> str:
    if key.get("fromMe"):
        return "Me"
    sender = data.get("pushName") or key.get("participant") or data.get("participant") or remote_jid
    return str(sender).split("@")[0] or "Unknown"


def _extract_group_name(data: dict[str, Any], remote_jid: str, is_group: bool) -> str:
    if not is_group:
        return data.get("pushName") or remote_jid.split("@")[0] or "Direct Message"
    return data.get("groupName") or data.get("groupSubject") or remote_jid.split("@")[0]


def _extract_message_content(message: dict[str, Any]) -> tuple[str, str]:
    if "conversation" in message:
        return str(message["conversation"]), "text"
    if "extendedTextMessage" in message:
        return str(message["extendedTextMessage"].get("text", "")), "text"
    if "imageMessage" in message:
        caption = message["imageMessage"].get("caption")
        return str(caption or "[Image Message]"), "media"
    if "videoMessage" in message:
        caption = message["videoMessage"].get("caption")
        return str(caption or "[Video Message]"), "media"
    if "documentMessage" in message:
        title = message["documentMessage"].get("title") or message["documentMessage"].get("fileName")
        return str(title or "[Document Message]"), "media"
    if "audioMessage" in message:
        return "[Audio Message]", "media"
    if "stickerMessage" in message:
        return "[Sticker Message]", "media"
    return "", "text"


def _save_evolution_media(base64_data: Any, message_id: str, file_ext: str) -> str | None:
    if not base64_data:
        return None
    try:
        encoded = str(base64_data)
        if "," in encoded:
            encoded = encoded.split(",", 1)[1]

        media_dir = Path(settings.data_dir) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", message_id)
        filename = f"{safe_id}_{int(time.time())}.{file_ext}"
        full_path = media_dir / filename

        with full_path.open("wb") as f:
            f.write(base64.b64decode(encoded))

        media_path = f"media/{filename}"
        print(f"DEBUG: Saved image to {media_path}")
        return media_path
    except Exception as e:
        print(f"DEBUG: Failed to save image: {e}")
        return None


def _get_or_create_live_batch(conn, group_id: int, now_iso: str) -> int:
    row = conn.execute(
        """
        SELECT id
        FROM import_batches
        WHERE group_id = ? AND file_name = 'LIVE_SYNC'
        ORDER BY id ASC
        LIMIT 1
        """,
        (group_id,),
    ).fetchone()
    if row:
        return int(row["id"])

    cursor = conn.execute(
        """
        INSERT INTO import_batches (
            group_id,
            file_name,
            file_sha1,
            imported_at,
            total_lines,
            parsed_messages,
            new_messages,
            duplicate_messages
        )
        VALUES (?, 'LIVE_SYNC', 'LIVE_SYNC', ?, 0, 0, 0, 0)
        """,
        (group_id, now_iso),
    )
    return int(cursor.lastrowid)


def _evolution_timestamp_to_iso(value: Any) -> str:
    if value is None:
        return datetime.now().isoformat()
    try:
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now().isoformat()


def _evolution_source_hash(remote_jid: str, message_id: str, timestamp: str, content: str) -> str:
    if message_id:
        return message_id
    payload = f"evolution|{remote_jid}|{timestamp}|{content}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def send_to_whatsapp(text: str, remote_jid: str) -> bool:
    """Sends a message to WhatsApp using Evolution API."""
    if not settings.evolution_api_key:
        print("DEBUG: Missing EVOLUTION_API_KEY")
        return False

    url = f"{settings.evolution_base_url.rstrip('/')}/message/sendText/{settings.evolution_instance}"
    req_data = json.dumps({
        "number": remote_jid,
        "options": {"delay": 1200, "presence": "composing", "linkPreview": False},
        "textMessage": {"text": text}
    }).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=req_data, headers={
            "Content-Type": "application/json",
            "apikey": settings.evolution_api_key
        })
        with urllib.request.urlopen(req, timeout=15) as response:
            resp = json.loads(response.read().decode("utf-8"))
            if resp.get("key"):
                print(f"DEBUG: Successfully sent message to WhatsApp {remote_jid}")
                return True
            else:
                print(f"DEBUG: Evolution API Error: {resp}")
    except Exception as e:
        print(f"DEBUG: Failed to send to WhatsApp: {e}")
    return False


def translate_to_thai(text: str) -> str:
    """Uses Gemini API to translate text to Thai."""
    if not settings.gemini_api_key:
        return text
        
    prompt = f"Translate the following WhatsApp message to professional and natural Thai language. Only return the translated text:\n\n{text}"
    
    req_data = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode("utf-8")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.gemini_api_key}"
    try:
        req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as response:
            resp_json = json.loads(response.read().decode("utf-8"))
            if "candidates" in resp_json and resp_json["candidates"]:
                return resp_json["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"Gemini Translation Error: {e}")
    return text


def send_to_slack(text: str, channel_id: str) -> None:
    """Sends a message to Slack using the Bot Token."""
    if not settings.slack_bot_token:
        print("DEBUG: Missing SLACK_BOT_TOKEN")
        return
        
    url = "https://slack.com/api/chat.postMessage"
    req_data = json.dumps({
        "channel": channel_id,
        "text": text
    }).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=req_data, headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {settings.slack_bot_token}"
        })
        with urllib.request.urlopen(req, timeout=10) as response:
            resp = json.loads(response.read().decode("utf-8"))
            if not resp.get("ok"):
                print(f"Slack API Error: {resp.get('error')}")
    except Exception as e:
        print(f"Slack Send Error: {e}")


@dataclass
class ImportResult:
    batch_id: int
    messages_count: int
    new_messages: int
    duplicate_messages: int
    group_name: str
    owner_name: str | None


def import_export_file(file_path: str, group_name: str, source_owner: str | None = None) -> ImportResult:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with path.open("r", encoding="utf-8") as f:
        content = f.read()

    return import_export_content(group_name, str(path.name), content, source_owner)


def import_export_content(group_name: str, file_name: str, content: str, source_owner: str | None = None) -> ImportResult:
    messages = parse_whatsapp_export(content)
    now_iso = utc_now_iso()
    file_sha1 = hashlib.sha1(content.encode("utf-8")).hexdigest()

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO groups (group_name, source_owner, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(group_name) DO UPDATE SET
                source_owner=COALESCE(excluded.source_owner, groups.source_owner)
            """,
            (group_name, source_owner, now_iso),
        )
        group_row = conn.execute("SELECT id FROM groups WHERE group_name = ?", (group_name,)).fetchone()
        group_id = int(group_row["id"])

        cursor = conn.execute(
            """
            INSERT INTO import_batches (
                group_id,
                file_name,
                file_sha1,
                imported_at,
                total_lines,
                parsed_messages,
                new_messages,
                duplicate_messages
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (group_id, file_name, file_sha1, now_iso, len(content.splitlines()), len(messages)),
        )
        batch_id = cursor.lastrowid

        new_messages = 0
        for msg in messages:
            sender_id = None
            if msg.sender_name:
                normalized_name = normalize_name(msg.sender_name)
                conn.execute(
                    """
                    INSERT INTO users (display_name, normalized_name, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(normalized_name) DO UPDATE SET
                        display_name=excluded.display_name
                    """,
                    (msg.sender_name, normalized_name, now_iso),
                )
                sender_row = conn.execute(
                    "SELECT id FROM users WHERE normalized_name = ?",
                    (normalized_name,),
                ).fetchone()
                sender_id = int(sender_row["id"])

            insert_cursor = conn.execute(
                """
                INSERT OR IGNORE INTO messages (
                    group_id,
                    sender_id,
                    batch_id,
                    sent_at,
                    message_type,
                    content_raw,
                    content_normalized,
                    source_hash,
                    source_line_start,
                    source_line_end,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    sender_id,
                    batch_id,
                    msg.sent_at.isoformat(),
                    msg.message_type,
                    msg.content_raw,
                    msg.content_normalized,
                    msg.source_hash,
                    msg.source_line_start,
                    msg.source_line_end,
                    now_iso,
                ),
            )
            new_messages += insert_cursor.rowcount

        duplicate_messages = len(messages) - new_messages
        conn.execute(
            """
            UPDATE import_batches
            SET new_messages = ?, duplicate_messages = ?
            WHERE id = ?
            """,
            (new_messages, duplicate_messages, batch_id),
        )
        conn.commit()
        return ImportResult(
            batch_id=batch_id,
            messages_count=len(messages),
            new_messages=new_messages,
            duplicate_messages=duplicate_messages,
            group_name=group_name,
            owner_name=source_owner
        )
    finally:
        conn.close()


def list_groups() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT DISTINCT group_name FROM groups").fetchall()
        return [{"name": r["group_name"]} for r in rows]
    finally:
        conn.close()


def list_import_batches(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                b.*,
                g.group_name
            FROM import_batches b
            JOIN groups g ON g.id = b.group_id
            ORDER BY b.imported_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_users(limit: int = 100) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                u.display_name,
                u.normalized_name,
                COUNT(m.id) AS msg_count
            FROM users u
            LEFT JOIN messages m ON u.id = m.sender_id
            GROUP BY u.id
            ORDER BY msg_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_messages(q: str | None = None, group_name: str | None = None, sender: str | None = None,
                   date_from: str | None = None, date_to: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        conditions = []
        params = []

        if q:
            search_terms = _extract_search_terms(q)
            term_conditions = []
            for term in search_terms:
                term_conditions.append("m.content_normalized LIKE ?")
                params.append(f"%{term}%")
            conditions.append("(" + " OR ".join(term_conditions) + ")")
        
        if group_name:
            conditions.append("m.group_id IN (SELECT id FROM groups WHERE group_name = ?)")
            params.append(group_name)
            
        if sender:
            conditions.append("m.sender_id IN (SELECT id FROM users WHERE display_name = ?)")
            params.append(sender)
            
        if date_from:
            conditions.append("m.sent_at >= ?")
            params.append(date_from)
            
        if date_to:
            conditions.append("m.sent_at <= ?")
            params.append(date_to)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT m.*, u.display_name as sender_name FROM messages m LEFT JOIN users u ON m.sender_id = u.id {where_clause} ORDER BY m.sent_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _extract_search_terms(q: str) -> list[str]:
    parts = re.split(r"\s+OR\s+", q, flags=re.IGNORECASE)
    terms: list[str] = []
    for part in parts:
        term = part.strip().strip('"').strip("'").lower()
        if term and term not in terms:
            terms.append(term)
    return terms or [q.strip().lower()]


def _configured_gemini_models() -> list[str]:
    models = [model.strip() for model in settings.gemini_models.split(",") if model.strip()]
    return models or ["gemini-2.5-flash-lite", "gemini-2.5-flash"]


def _build_deterministic_answer(question: str, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "ไม่พบข้อมูลที่เกี่ยวข้องในฐานข้อมูลแชท"

    lowered = question.lower()
    if _looks_like_latest_question(question):
        row = hits[0]
        return f"ข้อมูลล่าสุดที่พบคือ {row['sender_name'] or 'System'} เมื่อ {row['sent_at']}: {row['content_raw']}"

    if "ใคร" in question or "who" in lowered:
        names = []
        for row in hits:
            name = row["sender_name"] or "System"
            if name not in names:
                names.append(name)
        return "ผู้ที่เกี่ยวข้องจากข้อความที่พบ: " + ", ".join(names)

    if "สรุป" in question or "summary" in lowered or "summarize" in lowered:
        lines = []
        for row in hits[:5]:
            lines.append(f"- {row['sent_at']} | {row['sender_name'] or 'System'}: {row['content_raw']}")
        return "สรุปจากข้อความที่พบ:\n" + "\n".join(lines)

    row = hits[0]
    return f"พบข้อความที่เกี่ยวข้อง {len(hits)} รายการ รายการที่ตรงที่สุดคือ {row['sender_name'] or 'System'} เมื่อ {row['sent_at']}: {row['content_raw']}"


def _looks_like_latest_question(question: str) -> bool:
    lowered = question.lower()
    markers = ["ล่าสุด", "last", "latest", "recent", "เมื่อไหร่", "ครั้งสุดท้าย"]
    return any(marker in lowered for marker in markers)


def _summarize_api_error(error_body: str) -> str:
    try:
        payload = json.loads(error_body)
        message = payload.get("error", {}).get("message")
        if message:
            return str(message)[:240]
    except json.JSONDecodeError:
        pass
    return error_body.replace("\n", " ")[:240]


def ask_agent(question: str, group_name: str | None = None, sender: str | None = None,
             date_from: str | None = None, date_to: str | None = None, limit: int = 20) -> dict[str, Any]:
    search_q = _derive_search_query(question)
    hits = search_messages(
        q=search_q,
        group_name=group_name,
        sender=sender,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    
    if not hits:
        return {
            "question": question,
            "answer": "ขออภัยครับ ไม่พบข้อมูลที่เกี่ยวข้องในฐานข้อมูลแชทเลยครับ",
            "citations": [],
            "meta": {"matched_messages": 0, "search_query": search_q},
        }

    context_str = "\n".join([f"[{h['sent_at']}] {h['sender_name']}: {h['content_raw']}" for h in hits])
    
    prompt = f"""คุณคือ AI Assistant ที่เก่งกาจในการวิเคราะห์ข้อมูลแชท WhatsApp
ข้อมูลแชทต่อไปนี้คือบริบทที่ใช้ในการตอบคำถาม:
---
{context_str}
---
คำถาม: {question}

กรุณาตอบคำถามโดยใช้ข้อมูลจากแชทที่ให้มาเท่านั้น หากไม่มีข้อมูลให้บอกตรงๆ
ตอบเป็นภาษาไทยที่สุภาพและกระชับ
"""

    import time as _time
    gemini_key = settings.gemini_api_key
    answer = _build_deterministic_answer(question, hits)
    answer_source = "deterministic"

    if gemini_key:
        req_data = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}]
        }).encode("utf-8")

        for model in _configured_gemini_models():
            success = False
            for attempt in range(3):
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                    req = urllib.request.Request(
                        url, data=req_data,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=30) as response:
                        resp_json = json.loads(response.read().decode("utf-8"))
                        if "candidates" in resp_json and resp_json["candidates"]:
                            answer = resp_json["candidates"][0]["content"]["parts"][0]["text"]
                            answer_source = model
                        else:
                            answer = _build_deterministic_answer(question, hits)
                    success = True
                    break
                except urllib.error.HTTPError as e:
                    error_body = e.read().decode("utf-8")
                    print(f"Gemini {model} attempt {attempt+1}: HTTP {e.code} - {_summarize_api_error(error_body)}")
                    if e.code == 429 and attempt < 2:
                        _time.sleep(2 ** attempt)
                    else:
                        break
                except Exception as e:
                    print(f"Gemini {model} error: {e}")
                    break
            if success:
                break

    top_hits = hits[:3]
    citations = [
        {
            "sender": row["sender_name"],
            "sent_at": row["sent_at"],
            "content_raw": row["content_raw"],
        }
        for row in top_hits
    ]
    return {
        "question": question,
        "answer": answer,
        "citations": citations,
        "meta": {
            "matched_messages": len(hits),
            "search_query": search_q,
            "answer_source": answer_source,
        },
    }


def verify_slack_signature(timestamp: str, signature: str, raw_body: bytes) -> bool:
    if not settings.slack_signing_secret:
        return False
    basestring = f"v0:{timestamp}:".encode("utf-8") + raw_body
    h = hmac.new(settings.slack_signing_secret.encode("utf-8"), basestring, hashlib.sha256)
    expected_signature = f"v0={h.hexdigest()}"
    return hmac.compare_digest(expected_signature, signature)


def send_slack_delayed_response(response_url: str, payload: dict[str, Any]) -> None:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            response_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            pass
    except Exception as e:
        print(f"Error sending delayed response: {e}")


def handle_slack_command(text: str, channel_id: str | None = None, response_url: str | None = None) -> dict[str, Any]:
    print(f"Incoming Slack command: {text} in channel {channel_id}")
    
    # Check if channel is allowed
    allowed = [c.strip() for c in settings.slack_allowed_channels.split(",") if c.strip()]
    if allowed and channel_id not in allowed:
        return {
            "response_type": "ephemeral",
            "text": f"⚠️ บอทตัวนี้ไม่ได้ถูกอนุญาตให้ใช้งานในห้องนี้ (Channel ID: {channel_id})\nกรุณาติดต่อผู้ดูแลระบบเพื่อเปิดใช้งานครับ"
        }

    text = text.strip()
    if not text:
        return {"text": "💡 วิธีใช้: `/wa ask [คำถาม]` หรือ `/wa search [คำค้นหา]`"}

    # Run the processing in a background thread if we have a response_url
    if response_url:
        def worker():
            parts = text.split(" ", 1)
            cmd = parts[0].lower()
            
            if cmd == "ask" and len(parts) > 1:
                query = parts[1]
            elif cmd == "search" and len(parts) > 1:
                hits = search_messages(parts[1], limit=5)
                if not hits:
                    send_slack_delayed_response(response_url, {"text": f"❌ ไม่พบข้อมูลสำหรับ '{parts[1]}'"})
                    return
                lines = [f"• {h['sent_at']} | *{h['sender_name'] or 'System'}*: {h['content_raw']}" for h in hits]
                send_slack_delayed_response(response_url, {"text": f"🔍 ผลการค้นหา '{parts[1]}':\n" + "\n".join(lines)})
                return
            else:
                query = text

            try:
                result = ask_agent(query)
                send_slack_delayed_response(response_url, {
                    "response_type": "in_channel",
                    "text": result["answer"]
                })
            except Exception as e:
                print(f"Error in worker thread: {e}")
                send_slack_delayed_response(response_url, {"text": f"🚨 เกิดข้อผิดพลาด: {e}"})

        threading.Thread(target=worker).start()
        return {
            "response_type": "ephemeral", 
            "text": "🔍 กำลังประมวลผลคำตอบให้สักครู่นะครับ..."
        }

    return {"text": "Error: Missing response_url"}


def export_state() -> dict[str, Any]:
    return {"groups": list_groups(), "imports": list_import_batches()}


def database_status() -> dict[str, Any]:
    conn = get_connection()
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        counts: dict[str, int] = {}
        for table in ["groups", "users", "import_batches", "messages"]:
            if table in tables:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            else:
                counts[table] = 0
        return {
            "db_path": str(settings.db_path),
            "exists": Path(settings.db_path).exists(),
            "tables": sorted(tables),
            "counts": counts,
        }
    finally:
        conn.close()


def run_database_maintenance(action: str) -> dict[str, Any]:
    clean_action = action.strip().lower()
    if clean_action == "backup":
        return _backup_database()
    if clean_action == "cleanup_empty_live_batches":
        return _cleanup_empty_live_batches()
    if clean_action == "vacuum":
        return _vacuum_database()
    if clean_action == "sync_evolution_groups":
        return _sync_evolution_groups()
    raise ValueError(f"Unsupported maintenance action: {action}")


def _backup_database() -> dict[str, Any]:
    db_path = Path(settings.db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    backup_dir = Path(settings.data_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"whatsapp_agent_{timestamp}.db"

    source = sqlite3.connect(str(db_path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    return {
        "action": "backup",
        "backup_path": str(backup_path),
        "size_bytes": backup_path.stat().st_size,
    }


def _cleanup_empty_live_batches() -> dict[str, Any]:
    conn = get_connection()
    try:
        before = int(conn.execute("SELECT COUNT(*) AS count FROM import_batches").fetchone()["count"])
        target_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM import_batches
                WHERE file_name = 'LIVE_SYNC'
                  AND COALESCE(parsed_messages, 0) = 0
                  AND COALESCE(new_messages, 0) = 0
                  AND COALESCE(duplicate_messages, 0) = 0
                  AND id NOT IN (
                    SELECT DISTINCT batch_id
                    FROM messages
                    WHERE batch_id IS NOT NULL
                  )
                """
            ).fetchone()["count"]
        )
        cursor = conn.execute(
            """
            DELETE FROM import_batches
            WHERE file_name = 'LIVE_SYNC'
              AND COALESCE(parsed_messages, 0) = 0
              AND COALESCE(new_messages, 0) = 0
              AND COALESCE(duplicate_messages, 0) = 0
              AND id NOT IN (
                SELECT DISTINCT batch_id
                FROM messages
                WHERE batch_id IS NOT NULL
              )
            """
        )
        conn.commit()
        after = int(conn.execute("SELECT COUNT(*) AS count FROM import_batches").fetchone()["count"])
        return {
            "action": "cleanup_empty_live_batches",
            "deleted_rows": cursor.rowcount if cursor.rowcount >= 0 else target_count,
            "target_rows": target_count,
            "before_batches": before,
            "after_batches": after,
        }
    finally:
        conn.close()


def _vacuum_database() -> dict[str, Any]:
    db_path = Path(settings.db_path)
    before_size = db_path.stat().st_size if db_path.exists() else 0
    conn = get_connection()
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    after_size = db_path.stat().st_size if db_path.exists() else 0
    return {
        "action": "vacuum",
        "before_size_bytes": before_size,
        "after_size_bytes": after_size,
        "saved_bytes": max(before_size - after_size, 0),
    }


def _sync_evolution_groups() -> dict[str, Any]:
    if not settings.evolution_api_key:
        raise RuntimeError("EVOLUTION_API_KEY is not configured")

    groups = _fetch_evolution_groups()
    conn = get_connection()
    now_iso = utc_now_iso()
    stats = {
        "action": "sync_evolution_groups",
        "remote_groups": len(groups),
        "updated": 0,
        "renamed": 0,
        "merged": 0,
        "inserted": 0,
    }

    try:
        for group in groups:
            remote_jid = str(group.get("id") or "").strip()
            subject = str(group.get("subject") or "").strip()
            if not remote_jid.endswith("@g.us") or not subject:
                continue

            jid_key = remote_jid.split("@", 1)[0]
            numeric_row = conn.execute(
                "SELECT id, group_name FROM groups WHERE remote_jid = ? OR group_name = ? LIMIT 1",
                (remote_jid, jid_key),
            ).fetchone()
            subject_row = conn.execute(
                "SELECT id, group_name FROM groups WHERE group_name = ? LIMIT 1",
                (subject,),
            ).fetchone()

            target_row = numeric_row or subject_row
            if numeric_row and subject_row and int(numeric_row["id"]) != int(subject_row["id"]):
                target_id = int(numeric_row["id"])
                source_id = int(subject_row["id"])
                conn.execute("UPDATE messages SET group_id = ? WHERE group_id = ?", (target_id, source_id))
                conn.execute("UPDATE import_batches SET group_id = ? WHERE group_id = ?", (target_id, source_id))
                conn.execute("DELETE FROM groups WHERE id = ?", (source_id,))
                target_row = numeric_row
                stats["merged"] += 1

            if target_row:
                target_id = int(target_row["id"])
                desired_name = _unique_group_name(conn, subject, target_id, jid_key)
                if target_row["group_name"] != desired_name:
                    conn.execute("UPDATE groups SET group_name = ? WHERE id = ?", (desired_name, target_id))
                    stats["renamed"] += 1
                conn.execute("UPDATE groups SET remote_jid = ? WHERE id = ?", (remote_jid, target_id))
                stats["updated"] += 1
            else:
                group_name = _unique_group_name(conn, subject, None, jid_key)
                conn.execute(
                    """
                    INSERT INTO groups (group_name, remote_jid, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (group_name, remote_jid, now_iso),
                )
                stats["inserted"] += 1

        conn.commit()
        return stats
    finally:
        conn.close()


def _fetch_evolution_groups() -> list[dict[str, Any]]:
    url = (
        f"{settings.evolution_base_url.rstrip('/')}"
        f"/group/fetchAllGroups/{urllib.parse.quote(settings.evolution_instance)}?getParticipants=false"
    )
    req = urllib.request.Request(url, headers={"apikey": settings.evolution_api_key})
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    raise RuntimeError(f"Unexpected Evolution groups response: {str(payload)[:200]}")


def _unique_group_name(conn, desired_name: str, current_id: int | None, jid_key: str) -> str:
    row = conn.execute("SELECT id FROM groups WHERE group_name = ? LIMIT 1", (desired_name,)).fetchone()
    if not row or (current_id is not None and int(row["id"]) == current_id):
        return desired_name
    return f"{desired_name} ({jid_key[-6:]})"


def system_status() -> dict[str, Any]:
    load_average = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "status": "ok",
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "uptime_seconds": _read_uptime_seconds(),
        "load_average": list(load_average) if load_average else None,
        "memory": _read_memory_status(),
        "disk": {
            "data_dir": _disk_usage(settings.data_dir),
            "root": _disk_usage(Path("/")),
        },
        "temperature_c": _read_temperature_c(),
        "process": {
            "pid": os.getpid(),
            "cwd": os.getcwd(),
        },
        "app": {
            "host": settings.host,
            "port": settings.port,
            "data_dir": str(settings.data_dir),
            "db_path": str(settings.db_path),
        },
        "integrations": {
            "gemini_configured": bool(settings.gemini_api_key),
            "slack_bot_configured": bool(settings.slack_bot_token),
            "slack_signing_configured": bool(settings.slack_signing_secret),
            "evolution_configured": bool(settings.evolution_api_key),
            "evolution_base_url": settings.evolution_base_url,
            "evolution_reachable": _http_reachable(settings.evolution_base_url),
        },
    }


def docker_status() -> dict[str, Any]:
    if not settings.docker_socket:
        return {
            "available": False,
            "control_enabled": False,
            "containers": [],
            "error": "WA_AGENT_DOCKER_SOCKET is not configured",
        }

    if not Path(settings.docker_socket).exists():
        return {
            "available": False,
            "control_enabled": False,
            "containers": [],
            "error": f"Docker socket not found: {settings.docker_socket}",
        }

    try:
        containers = _docker_containers()
        return {
            "available": True,
            "control_enabled": settings.docker_control_enabled,
            "containers": containers,
            "error": None,
        }
    except Exception as exc:
        return {
            "available": False,
            "control_enabled": settings.docker_control_enabled,
            "containers": [],
            "error": _redact_sensitive_text(str(exc)),
        }


def docker_container_logs(name: str, tail: int = 120) -> dict[str, Any]:
    container = _resolve_allowed_container(name)
    tail = max(10, min(int(tail), 500))
    query = urllib.parse.urlencode(
        {
            "stdout": "1",
            "stderr": "1",
            "timestamps": "1",
            "tail": str(tail),
        }
    )
    raw = _docker_request_bytes("GET", f"/containers/{urllib.parse.quote(container['id'])}/logs?{query}")
    text = _decode_docker_log_stream(raw)
    return {
        "name": container["name"],
        "logs": _redact_sensitive_text(text),
        "tail": tail,
    }


def restart_docker_container(name: str) -> dict[str, Any]:
    if not settings.docker_control_enabled:
        raise PermissionError("Docker control is disabled")

    container = _resolve_allowed_container(name)
    _docker_request_bytes("POST", f"/containers/{urllib.parse.quote(container['id'])}/restart?t=10", expected_statuses={204})
    return {
        "status": "restarted",
        "name": container["name"],
    }


def _docker_allowed_names() -> list[str]:
    return [name.strip() for name in settings.docker_allowlist.split(",") if name.strip()]


def _docker_containers() -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"all": "1"})
    data = _docker_request_json("GET", f"/containers/json?{query}") or []
    allowed_names = _docker_allowed_names()
    allowed_set = set(allowed_names)
    containers: list[dict[str, Any]] = []

    for item in data:
        raw_names = [str(name).lstrip("/") for name in item.get("Names", [])]
        if allowed_set and not allowed_set.intersection(raw_names):
            continue

        name = next((candidate for candidate in allowed_names if candidate in raw_names), raw_names[0] if raw_names else item.get("Id", "")[:12])
        containers.append(
            {
                "id": str(item.get("Id", ""))[:12],
                "name": name,
                "image": item.get("Image"),
                "state": item.get("State"),
                "status": item.get("Status"),
                "ports": _format_docker_ports(item.get("Ports") or []),
                "restart_allowed": settings.docker_control_enabled and name in allowed_set,
            }
        )

    order = {name: index for index, name in enumerate(allowed_names)}
    containers.sort(key=lambda item: order.get(item["name"], 999))
    return containers


def _resolve_allowed_container(name: str) -> dict[str, str]:
    clean_name = name.strip()
    allowed = set(_docker_allowed_names())
    if not clean_name or clean_name not in allowed:
        raise ValueError("Container is not allowed")

    for container in _docker_containers():
        if container["name"] == clean_name:
            return {"id": container["id"], "name": container["name"]}

    raise ValueError(f"Container not found: {clean_name}")


def _format_docker_ports(ports: list[dict[str, Any]]) -> list[str]:
    formatted: list[str] = []
    for port in ports:
        private_port = port.get("PrivatePort")
        public_port = port.get("PublicPort")
        port_type = port.get("Type", "tcp")
        if public_port:
            label = f"{public_port}->{private_port}/{port_type}"
        elif private_port:
            label = f"{private_port}/{port_type}"
        else:
            continue
        if label not in formatted:
            formatted.append(label)
    return formatted


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 5) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


def _docker_request_json(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    raw = _docker_request_bytes(method, path, body=body)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _docker_request_bytes(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    expected_statuses: set[int] | None = None,
) -> bytes:
    if not settings.docker_socket:
        raise RuntimeError("Docker socket is not configured")

    expected = expected_statuses or {200}
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    conn = _UnixHTTPConnection(settings.docker_socket, timeout=6)
    try:
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        if response.status not in expected:
            detail = _redact_sensitive_text(raw.decode("utf-8", errors="replace"))
            raise RuntimeError(f"Docker API {response.status}: {detail or response.reason}")
        return raw
    finally:
        conn.close()


def _decode_docker_log_stream(raw: bytes) -> str:
    chunks: list[bytes] = []
    index = 0
    while index + 8 <= len(raw) and raw[index] in {1, 2, 3} and raw[index + 1:index + 4] == b"\x00\x00\x00":
        frame_size = int.from_bytes(raw[index + 4:index + 8], "big")
        index += 8
        chunks.append(raw[index:index + frame_size])
        index += frame_size

    if chunks and index == len(raw):
        raw = b"".join(chunks)

    return raw.decode("utf-8", errors="replace")


def _redact_sensitive_text(text: str) -> str:
    patterns = [
        (r"(?i)(secret=)[^&\s'\",}]+", r"\1<redacted>"),
        (r"(?i)(apikey['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._~:/+=-]+", r"\1<redacted>"),
        (r"(?i)((?:api[_-]?key|token|secret|password)['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._~:/+=-]+", r"\1<redacted>"),
        (r"xox[baprs]-[A-Za-z0-9-]+", "xox-<redacted>"),
    ]
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def _read_uptime_seconds() -> float | None:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _read_memory_status() -> dict[str, int | float] | None:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            parts = raw_value.strip().split()
            if parts:
                values[key] = int(parts[0]) * 1024

        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if not total or available is None:
            return None

        used = total - available
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": used,
            "used_percent": round((used / total) * 100, 1),
        }
    except (OSError, ValueError):
        return None


def _disk_usage(path: Path) -> dict[str, int | float | str] | None:
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": str(path),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
        }
    except OSError:
        return None


def _read_temperature_c() -> float | None:
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            raw = path.read_text().strip()
            if raw:
                return round(float(raw) / 1000, 1)
        except (OSError, ValueError):
            continue
    return None


def _http_reachable(url: str) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url.rstrip("/"), method="GET")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _derive_search_query(question: str) -> str:
    lowered = question.lower()
    tokens: list[str] = []
    sku_like_tokens = [match.lower() for match in re.findall(r"[a-zA-Z]{2,}-\d{1,}", question)]
    if sku_like_tokens:
        return " OR ".join(dict.fromkeys(sku_like_tokens))

    keyword_map = {
        "สั่ง": ["order"],
        "ออเดอร์": ["order"],
        "สินค้า": ["sku", "unit"],
        "ส่งของ": ["shipment", "delivery"],
        "จัดส่ง": ["shipment", "delivery"],
        "ช้า": ["delay", "delayed"],
        "ล่าช้า": ["delay", "delayed"],
        "ลูกค้า": ["client", "customer"],
        "สต็อก": ["stock"],
        "สต๊อก": ["stock"],
    }
    for thai_word, english_hints in keyword_map.items():
        if thai_word in question:
            tokens.extend(english_hints)

    stop_words = {
        "who", "what", "when", "where", "why", "how", "the", "and", "for",
        "with", "that", "this", "please", "latest", "last", "recent",
        "summarize", "summary", "all",
    }
    english_words = re.findall(r"[a-zA-Z0-9]{3,}", lowered)
    tokens.extend(word for word in english_words if word not in stop_words)

    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)

    return " OR ".join(deduped) if deduped else lowered.strip()
