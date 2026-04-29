from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from .db import get_connection, init_db, utc_now_iso
from .parser import ParsedMessage, normalize_name, parse_whatsapp_export


@dataclass
class ImportResult:
    batch_id: int
    group_name: str
    file_name: str
    total_lines: int
    parsed_messages: int
    new_messages: int
    duplicate_messages: int


def ensure_ready() -> None:
    init_db()


def ensure_group(conn, group_name: str, source_owner: str | None = None, timezone: str = "Asia/Bangkok") -> int:
    row = conn.execute("SELECT id FROM groups WHERE group_name = ?", (group_name.strip(),)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO groups (group_name, source_owner, timezone, created_at) VALUES (?, ?, ?, ?)",
        (group_name.strip(), source_owner, timezone, utc_now_iso()),
    )
    return int(cur.lastrowid)


def ensure_user(conn, display_name: str | None) -> int | None:
    if not display_name:
        return None
    normalized_name = normalize_name(display_name)
    row = conn.execute("SELECT id FROM users WHERE normalized_name = ?", (normalized_name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO users (display_name, normalized_name, created_at) VALUES (?, ?, ?)",
        (display_name.strip(), normalized_name, utc_now_iso()),
    )
    return int(cur.lastrowid)


def import_export_content(group_name: str, file_name: str, content: str, source_owner: str | None = None) -> ImportResult:
    ensure_ready()
    parsed = parse_whatsapp_export(content)
    file_sha1 = hashlib.sha1(content.encode("utf-8")).hexdigest()
    lines = content.splitlines()

    with get_connection() as conn:
        group_id = ensure_group(conn, group_name, source_owner=source_owner)
        batch_cur = conn.execute(
            """
            INSERT INTO import_batches (
                group_id, file_name, file_sha1, imported_at, total_lines, parsed_messages, new_messages, duplicate_messages
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (group_id, file_name, file_sha1, utc_now_iso(), len(lines), len(parsed)),
        )
        batch_id = int(batch_cur.lastrowid)

        new_messages = 0
        duplicate_messages = 0
        for item in parsed:
            exists = conn.execute("SELECT id FROM messages WHERE source_hash = ?", (item.source_hash,)).fetchone()
            if exists:
                duplicate_messages += 1
                continue
            sender_id = ensure_user(conn, item.sender_name)
            conn.execute(
                """
                INSERT INTO messages (
                    group_id, sender_id, batch_id, sent_at, message_type, content_raw,
                    content_normalized, content_th, source_hash, source_line_start, source_line_end, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    sender_id,
                    batch_id,
                    item.sent_at.isoformat(sep=" "),
                    item.message_type,
                    item.content_raw,
                    item.content_normalized,
                    item.source_hash,
                    item.source_line_start,
                    item.source_line_end,
                    utc_now_iso(),
                ),
            )
            new_messages += 1

        conn.execute(
            "UPDATE import_batches SET new_messages = ?, duplicate_messages = ? WHERE id = ?",
            (new_messages, duplicate_messages, batch_id),
        )
        conn.commit()

    return ImportResult(
        batch_id=batch_id,
        group_name=group_name,
        file_name=file_name,
        total_lines=len(lines),
        parsed_messages=len(parsed),
        new_messages=new_messages,
        duplicate_messages=duplicate_messages,
    )


def import_export_file(path: str | Path, group_name: str, source_owner: str | None = None) -> ImportResult:
    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8")
    return import_export_content(group_name=group_name, file_name=file_path.name, content=content, source_owner=source_owner)


def list_groups() -> list[dict[str, Any]]:
    ensure_ready()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT g.id, g.group_name, g.timezone, g.source_owner, g.created_at, COUNT(m.id) AS message_count
            FROM groups g
            LEFT JOIN messages m ON m.group_id = g.id
            GROUP BY g.id
            ORDER BY g.group_name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_import_batches(limit: int = 20) -> list[dict[str, Any]]:
    ensure_ready()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT b.id, g.group_name, b.file_name, b.imported_at, b.parsed_messages, b.new_messages, b.duplicate_messages
            FROM import_batches b
            JOIN groups g ON g.id = b.group_id
            ORDER BY b.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def search_messages(
    q: str | None = None,
    *,
    group_name: str | None = None,
    sender: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ensure_ready()
    sql = """
        SELECT
            m.id,
            g.group_name,
            u.display_name AS sender_name,
            m.sent_at,
            m.message_type,
            m.content_raw,
            m.content_normalized,
            m.source_line_start,
            m.source_line_end
        FROM messages m
        JOIN groups g ON g.id = m.group_id
        LEFT JOIN users u ON u.id = m.sender_id
        WHERE 1 = 1
    """
    params: list[Any] = []

    if group_name:
        sql += " AND g.group_name = ?"
        params.append(group_name.strip())
    if sender:
        sql += " AND u.normalized_name = ?"
        params.append(normalize_name(sender))
    if date_from:
        sql += " AND m.sent_at >= ?"
        params.append(_to_iso_boundary(date_from, is_end=False))
    if date_to:
        sql += " AND m.sent_at <= ?"
        params.append(_to_iso_boundary(date_to, is_end=True))

    tokens = [token for token in (q or "").lower().split() if token]
    if tokens:
        sql += " AND (" + " OR ".join("m.content_normalized LIKE ?" for _ in tokens) + ")"
        params.extend(f"%{token}%" for token in tokens)

    sql += " ORDER BY m.sent_at DESC LIMIT ?"
    params.append(max(1, min(limit, 100)))

    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    return rows


def ask_agent(
    question: str,
    *,
    group_name: str | None = None,
    sender: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    derived_query = _derive_search_query(question)
    hits = search_messages(
        q=derived_query,
        group_name=group_name,
        sender=sender,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    if not hits:
        return {
            "question": question,
            "answer": "ไม่พบข้อความที่ตรงกับคำถามในฐานข้อมูลตอนนี้",
            "citations": [],
            "meta": {"matched_messages": 0},
        }

    top_hits = hits[: min(5, len(hits))]
    senders = [row["sender_name"] or "System" for row in top_hits]
    sender_summary = ", ".join(name for name, _ in Counter(senders).most_common(3))

    lines = []
    for row in top_hits:
        timestamp = _human_time(row["sent_at"])
        sender_name = row["sender_name"] or "System"
        snippet = row["content_raw"].replace("\n", " ").strip()
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        lines.append(f"- {timestamp} | {sender_name} | {snippet}")

    intro = f"พบข้อความที่เกี่ยวข้อง {len(hits)} รายการ"
    if sender_summary:
        intro += f" โดยผู้ที่เกี่ยวข้องหลักคือ {sender_summary}"

    answer = intro + "\n" + "\n".join(lines)
    lowered_question = question.lower()
    if "ใคร" in question and ("ล่าสุด" in question or "last" in lowered_question):
        latest = top_hits[0]
        latest_sender = latest["sender_name"] or "System"
        latest_time = _human_time(latest["sent_at"])
        latest_content = latest["content_raw"].replace("\n", " ")
        answer = (
            f"ข้อความล่าสุดที่เกี่ยวข้องคือ {latest_sender} เมื่อ {latest_time}\n"
            f"เนื้อหา: {latest_content}\n"
            + "\n".join(lines)
        )
    elif "สรุป" in question:
        answer = (
            f"สรุปจากข้อความที่ค้นเจอ {len(hits)} รายการ\n"
            f"ผู้เกี่ยวข้องหลัก: {sender_summary}\n"
            + "\n".join(lines)
        )

    citations = [
        {
            "message_id": row["id"],
            "group_name": row["group_name"],
            "sender_name": row["sender_name"],
            "sent_at": row["sent_at"],
            "source_lines": [row["source_line_start"], row["source_line_end"]],
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


def export_state() -> dict[str, Any]:
    return {"groups": list_groups(), "imports": list_import_batches()}


def _to_iso_boundary(date_value: str, *, is_end: bool) -> str:
    parsed = datetime.strptime(date_value, "%Y-%m-%d")
    if is_end:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed.isoformat(sep=" ")


def _human_time(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


def _derive_search_query(question: str) -> str:
    lowered = question.lower()
    tokens: list[str] = []

    # Preserve structured business tokens like SKU IDs or order codes.
    tokens.extend(match.lower() for match in re.findall(r"[a-zA-Z]{2,}-\d{1,}", question))

    keyword_map = {
        "สั่ง": "order",
        "สินค้า": "sku",
        "ส่งของ": "shipment",
        "ช้า": "delay",
        "ล่าช้า": "delay",
        "สรุป": "summary",
        "ลูกค้า": "client",
        "สต็อก": "stock",
    }
    for thai_word, english_hint in keyword_map.items():
        if thai_word in question:
            tokens.append(english_hint)

    if "delay" in lowered:
        tokens.append("delayed")
    if "shipment" in lowered:
        tokens.append("supplier")

    english_words = re.findall(r"[a-zA-Z0-9]{3,}", lowered)
    tokens.extend(english_words)

    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)

    if deduped:
        return " ".join(deduped)
    return question
