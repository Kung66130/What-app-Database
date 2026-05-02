from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any
import json
import urllib.request
import urllib.error
import hmac
import hashlib
import threading

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
    
    # 1. Extract basic info
    remote_jid = key.get("remoteJid", "")
    is_group = "@g.us" in remote_jid
    sender_name = data.get("pushName") or "Unknown"
    
    # Extract content (handling different message types)
    content = ""
    if "conversation" in message:
        content = message["conversation"]
    elif "extendedTextMessage" in message:
        content = message["extendedTextMessage"].get("text", "")
    elif "imageMessage" in message:
        content = "[Image Message]"
    elif "videoMessage" in message:
        content = "[Video Message]"
    elif "documentMessage" in message:
        content = "[Document Message]"
    
    if not content and not is_group:
         return {"status": "ignored", "reason": "empty_content"}

    # 2. Identify Group
    group_name = "Direct Message"
    if is_group:
        # Evolution API usually provides group name in another field or we can use JID
        # For now, let's use the JID as a placeholder or check if group metadata is present
        group_name = data.get("groupName") or remote_jid.split("@")[0]

    # 3. Store in DB
    conn = get_connection()
    try:
        now_iso = datetime.now().isoformat()
        
        # Upsert Group
        conn.execute("INSERT OR IGNORE INTO groups (group_name, created_at) VALUES (?, ?)", (group_name, now_iso))
        group_id = conn.execute("SELECT id FROM groups WHERE group_name = ?", (group_name,)).fetchone()["id"]

        # Upsert User
        conn.execute("INSERT OR IGNORE INTO users (display_name, normalized_name, created_at) VALUES (?, ?, ?)", (sender_name, sender_name.lower(), now_iso))
        sender_id = conn.execute("SELECT id FROM users WHERE normalized_name = ?", (sender_name.lower(),)).fetchone()["id"]

        # Ensure Batch
        conn.execute("INSERT OR IGNORE INTO import_batches (group_id, file_name, file_sha1, imported_at, total_lines, parsed_messages, new_messages, duplicate_messages) VALUES (?, 'LIVE_SYNC', 'LIVE_SYNC', ?, 0, 0, 0, 0)", (group_id, now_iso))
        batch_id = conn.execute("SELECT id FROM import_batches WHERE group_id = ? AND file_name = 'LIVE_SYNC' LIMIT 1", (group_id,)).fetchone()["id"]

        # Insert Message
        timestamp = datetime.fromtimestamp(data.get("messageTimestamp", datetime.now().timestamp())).isoformat()
        source_hash = key.get("id", str(datetime.now().timestamp()))
        
        conn.execute(
            """
            INSERT OR IGNORE INTO messages (group_id, sender_id, batch_id, sent_at, message_type, content_raw, content_normalized, source_hash, source_line_start, source_line_end, created_at)
            VALUES (?, ?, ?, ?, 'text', ?, ?, ?, 0, 0, ?)
            """,
            (group_id, sender_id, batch_id, timestamp, content, content.lower(), source_hash, now_iso)
        )
        conn.commit()
        return {"status": "success", "message_id": key.get("id")}
    finally:
        conn.close()


@dataclass
class ImportResult:
    batch_id: int
    messages_count: int
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
    
    conn = get_connection()
    try:
        # 1. Create Import Batch
        cursor = conn.execute(
            "INSERT INTO import_batches (group_name, owner_name, source_file) VALUES (?, ?, ?)",
            (group_name, source_owner, file_name)
        )
        batch_id = cursor.lastrowid
        
        # 2. Insert Users and Messages
        for msg in messages:
            # Upsert User
            conn.execute("INSERT OR IGNORE INTO users (name) VALUES (?)", (msg.sender,))
            
            # Insert Message
            conn.execute(
                """
                INSERT INTO messages (batch_id, sent_at, sender_name, content_raw)
                VALUES (?, ?, ?, ?)
                """,
                (batch_id, msg.timestamp, msg.sender, msg.content)
            )
        
        conn.commit()
        return ImportResult(
            batch_id=batch_id,
            messages_count=len(messages),
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


def list_import_batches() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM import_batches ORDER BY imported_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_users() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT u.name, COUNT(m.id) as msg_count 
            FROM users u
            LEFT JOIN messages m ON u.name = m.sender_name
            GROUP BY u.name
            ORDER BY msg_count DESC
            """
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
            # Use FTS5 for search via subquery
            conditions.append("m.id IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)")
            params.append(q)
        
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


def ask_agent(question: str, group_name: str | None = None, sender: str | None = None,
             date_from: str | None = None, date_to: str | None = None, limit: int = 20) -> dict[str, Any]:
    # 1. Retrieve Context
    # Use a simplified search query derived from the question
    search_q = _derive_search_query(question)
    hits = search_messages(q=search_q, group_name=group_name, sender=sender, 
                          date_from=date_from, date_to=date_to, limit=limit)
    
    if not hits:
        return {
            "question": question,
            "answer": "ขออภัยครับ ไม่พบข้อมูลที่เกี่ยวข้องในฐานข้อมูลแชทเลยครับ",
            "citations": []
        }

    # 2. Build Prompt for Gemini
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

    # 3. Call Google Gemini Flash API (Free, Fast, High Quality)
    import time as _time
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    answer = "ขออภัยครับ ไม่สามารถเชื่อมต่อกับ Gemini AI ได้ในขณะนี้"

    if not gemini_key:
        answer = "ขออภัยครับ ไม่ได้ตั้งค่า GEMINI_API_KEY"
    else:
        req_data = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}]
        }).encode("utf-8")

        # Try models in order, with retry on 429
        for model in ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.0-flash"]:
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
                        else:
                            answer = "ขออภัยครับ AI ไม่สามารถสร้างคำตอบได้ในขณะนี้"
                    success = True
                    break
                except urllib.error.HTTPError as e:
                    print(f"Gemini {model} attempt {attempt+1}: HTTP {e.code}")
                    if e.code == 429 and attempt < 2:
                        _time.sleep(2 ** attempt)
                    else:
                        break
                except Exception as e:
                    print(f"Gemini {model} error: {e}")
                    break
            if success:
                break


    # 4. Format Citations
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
        "meta": {"matched_messages": len(hits)},
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


def _derive_search_query(question: str) -> str:
    lowered = question.lower()
    tokens: list[str] = []
    tokens.extend(match.lower() for match in re.findall(r"[a-zA-Z]{2,}-\d{1,}", question))

    keyword_map = {
        "สั่ง": "order",
        "สินค้า": "sku",
        "ส่งของ": "shipment",
        "ช้า": "delay",
        "ล่าช้า": "delay",
        "ลูกค้า": "client",
        "สต็อก": "stock",
    }
    for thai_word, english_hint in keyword_map.items():
        if thai_word in question:
            tokens.append(english_hint)

    english_words = re.findall(r"[a-zA-Z0-9]{3,}", lowered)
    tokens.extend(english_words)

    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)

    return " OR ".join(deduped) if deduped else ""
