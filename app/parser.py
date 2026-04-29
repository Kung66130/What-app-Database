from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime


MESSAGE_RE = re.compile(
    r"^\[?(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s+(?P<time>\d{1,2}:\d{2})(?:\s?(?P<ampm>AM|PM|am|pm))?\]?\s+-\s+(?P<body>.+)$"
)


@dataclass
class ParsedMessage:
    sent_at: datetime
    sender_name: str | None
    message_type: str
    content_raw: str
    content_normalized: str
    source_hash: str
    source_line_start: int
    source_line_end: int


def normalize_text(text: str) -> str:
    text = text.replace("\u200e", " ").replace("\u202f", " ")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def normalize_name(name: str) -> str:
    return normalize_text(name)


def parse_timestamp(date_part: str, time_part: str, ampm: str | None) -> datetime:
    year_digits = len(date_part.split("/")[-1])
    formats = []
    if ampm:
        formats.append("%d/%m/%Y %I:%M %p" if year_digits == 4 else "%d/%m/%y %I:%M %p")
    formats.append("%d/%m/%Y %H:%M" if year_digits == 4 else "%d/%m/%y %H:%M")
    value = f"{date_part} {time_part}" + (f" {ampm.upper()}" if ampm else "")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported WhatsApp timestamp: {value}")


def split_sender_and_content(body: str) -> tuple[str | None, str, str]:
    if ": " not in body:
        return None, body.strip(), "system"
    sender, content = body.split(": ", 1)
    content = content.strip()
    message_type = "media" if "<Media omitted>" in content else "text"
    return sender.strip(), content, message_type


def parse_whatsapp_export(content: str) -> list[ParsedMessage]:
    messages: list[ParsedMessage] = []
    current: dict[str, object] | None = None

    lines = content.splitlines()
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")
        match = MESSAGE_RE.match(line.strip())
        if match:
            if current is not None:
                messages.append(_build_parsed_message(current))
            sent_at = parse_timestamp(match.group("date"), match.group("time"), match.group("ampm"))
            sender_name, content_raw, message_type = split_sender_and_content(match.group("body"))
            current = {
                "sent_at": sent_at,
                "sender_name": sender_name,
                "message_type": message_type,
                "content_lines": [content_raw],
                "source_line_start": idx,
                "source_line_end": idx,
            }
            continue

        if current is not None:
            current["content_lines"].append(line)
            current["source_line_end"] = idx

    if current is not None:
        messages.append(_build_parsed_message(current))
    return messages


def _build_parsed_message(raw: dict[str, object]) -> ParsedMessage:
    content_raw = "\n".join(str(line) for line in raw["content_lines"]).strip()
    normalized = normalize_text(content_raw)
    payload = "|".join(
        [
            str(raw["sent_at"]),
            str(raw["sender_name"] or ""),
            normalized,
            str(raw["source_line_start"]),
            str(raw["source_line_end"]),
        ]
    )
    source_hash = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return ParsedMessage(
        sent_at=raw["sent_at"],  # type: ignore[arg-type]
        sender_name=raw["sender_name"],  # type: ignore[arg-type]
        message_type=str(raw["message_type"]),
        content_raw=content_raw,
        content_normalized=normalized,
        source_hash=source_hash,
        source_line_start=int(raw["source_line_start"]),
        source_line_end=int(raw["source_line_end"]),
    )
