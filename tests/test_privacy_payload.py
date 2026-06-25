from app.payload import redact_payload


def test_redacts_chat_message_content(monkeypatch):
    redactor = lambda text: text.replace("john@example.com", "[EMAIL]")

    payload = {"messages": [{"role": "user", "content": "Email john@example.com"}]}

    assert redact_payload(payload, redactor)["messages"][0]["content"] == "Email [EMAIL]"


def test_redacts_multimodal_text_parts(monkeypatch):
    redactor = lambda text: text.replace("555-0100", "[PHONE_NUMBER]")

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Call 555-0100"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
                ],
            }
        ]
    }

    redacted = redact_payload(payload, redactor)

    assert redacted["messages"][0]["content"][0]["text"] == "Call [PHONE_NUMBER]"
    assert redacted["messages"][0]["content"][1]["type"] == "image_url"


def test_redacts_responses_input(monkeypatch):
    redactor = lambda text: text.replace("Alice", "[PERSON]")

    assert redact_payload({"input": "Hello Alice"}, redactor)["input"] == "Hello [PERSON]"
