"""PII detection and redaction utilities."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

DEFAULT_MODEL = "fastino/gliner2-privacy-filter-PII-multi"
DEFAULT_LABELS = [
    "person",
    "full_name",
    "first_name",
    "middle_name",
    "last_name",
    "date_of_birth",
    "email",
    "phone_number",
    "address",
    "street_address",
    "city",
    "state_or_region",
    "postal_code",
    "country",
    "government_id",
    "national_id_number",
    "passport_number",
    "drivers_license_number",
    "license_number",
    "tax_id",
    "tax_number",
    "bank_account",
    "account_number",
    "routing_number",
    "iban",
    "payment_card",
    "card_number",
    "card_expiry",
    "card_cvv",
    "username",
    "ip_address",
    "account_id",
    "sensitive_account_id",
    "password",
    "secret",
    "api_key",
    "access_token",
    "recovery_code",
    "sensitive_date",
    "document_date",
    "expiration_date",
    "transaction_date",
]


def configured_labels() -> list[str]:
    labels = os.getenv("PII_LABELS")
    if not labels:
        return DEFAULT_LABELS
    return [label.strip() for label in labels.split(",") if label.strip()]


@lru_cache(maxsize=1)
def get_model() -> Any:
    from gliner2 import GLiNER2

    return GLiNER2.from_pretrained(os.getenv("GLINER2_MODEL", DEFAULT_MODEL))


def _entity_spans(text: str, result: Any) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    if isinstance(result, dict):
        entities = result.get("entities", result)
        for label, values in entities.items():
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, dict):
                    start, end = value.get("start"), value.get("end")
                    entity_text = value.get("text") or value.get("value")
                    entity_label = value.get("label", label)
                else:
                    start, end, entity_text, entity_label = None, None, str(value), label
                if isinstance(start, int) and isinstance(end, int):
                    spans.append((start, end, str(entity_label)))
                elif entity_text:
                    index = text.find(str(entity_text))
                    if index != -1:
                        spans.append((index, index + len(str(entity_text)), str(entity_label)))
    return spans


def detect_pii(text: str, threshold: float | None = None) -> list[tuple[int, int, str]]:
    threshold = float(os.getenv("PII_THRESHOLD", "0.5")) if threshold is None else threshold
    result = get_model().extract_entities(
        text,
        configured_labels(),
        threshold=threshold,
        include_confidence=True,
        include_spans=True,
    )
    return _entity_spans(text, result)


def redact_text(text: str, threshold: float | None = None) -> str:
    spans = detect_pii(text, threshold)
    redacted = text
    for start, end, label in sorted(spans, key=lambda span: span[0], reverse=True):
        redacted = f"{redacted[:start]}[{label.upper()}]{redacted[end:]}"
    return redacted
