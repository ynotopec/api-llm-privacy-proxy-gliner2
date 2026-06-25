"""Request payload redaction helpers."""

from __future__ import annotations

from typing import Any, Callable

from app.privacy import redact_text

Redactor = Callable[[str], str]


def redact_message_content(content: Any, redactor: Redactor = redact_text) -> Any:
    if isinstance(content, str):
        return redactor(content)
    if isinstance(content, list):
        redacted_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                part = {**part, "text": redactor(part["text"])}
            redacted_parts.append(part)
        return redacted_parts
    return content


def redact_payload(payload: Any, redactor: Redactor = redact_text) -> Any:
    if not isinstance(payload, dict):
        return payload
    redacted = dict(payload)
    if isinstance(redacted.get("messages"), list):
        redacted["messages"] = [
            {**message, "content": redact_message_content(message.get("content"), redactor)}
            if isinstance(message, dict)
            else message
            for message in redacted["messages"]
        ]
    if isinstance(redacted.get("input"), str):
        redacted["input"] = redactor(redacted["input"])
    return redacted
