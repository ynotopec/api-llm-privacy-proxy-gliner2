"""OpenAI-compatible LLM privacy proxy."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import load_env_file
from app.payload import redact_payload
from app.privacy import DEFAULT_MODEL

load_env_file()

app = FastAPI(title="LLM Privacy Proxy GLiNER2", version="0.1.0")

UPSTREAM_BASE_URL = os.getenv("UPSTREAM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY") or os.getenv("OPENAI_API_KEY")
PROXY_API_TOKEN = os.getenv("PROXY_API_TOKEN") or os.getenv("API_TOKEN")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "pii_model": os.getenv("GLINER2_MODEL", DEFAULT_MODEL)}


def _check_proxy_token(request: Request) -> None:
    if not PROXY_API_TOKEN:
        return
    auth_header = request.headers.get("authorization", "")
    expected = f"Bearer {PROXY_API_TOKEN}"
    if auth_header != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing proxy API token")


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> StreamingResponse:
    _check_proxy_token(request)
    if not UPSTREAM_API_KEY:
        raise HTTPException(status_code=500, detail="UPSTREAM_API_KEY or OPENAI_API_KEY must be configured")

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "authorization"}
    }
    headers["authorization"] = f"Bearer {UPSTREAM_API_KEY}"

    json_payload = None
    content = await request.body()
    if content and request.headers.get("content-type", "").startswith("application/json"):
        json_payload = redact_payload(await request.json())
        content = None

    client = httpx.AsyncClient(timeout=None)
    upstream_request = client.build_request(
        request.method,
        f"{UPSTREAM_BASE_URL}/{path}",
        params=request.query_params,
        headers=headers,
        content=content or None,
        json=json_payload,
    )
    upstream_response = await client.send(upstream_request, stream=True)

    async def body_iterator():
        try:
            async for chunk in upstream_response.aiter_bytes():
                yield chunk
        finally:
            await upstream_response.aclose()
            await client.aclose()

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in {"content-encoding", "transfer-encoding", "connection"}
    }
    return StreamingResponse(body_iterator(), status_code=upstream_response.status_code, headers=response_headers)
