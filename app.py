from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask

from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(level=LOG_LEVEL)
log = logging.getLogger("llm-privacy-proxy")


@dataclass
class Settings:
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8088"))
    inbound_api_keys: list[str] = field(
        default_factory=lambda: [x.strip() for x in os.getenv("INBOUND_API_KEYS", "").split(",") if x.strip()]
    )
    upstream_base_url: str = os.getenv("UPSTREAM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    upstream_api_key: str = os.getenv("UPSTREAM_API_KEY", "")
    privacy_model_id: str = os.getenv("PRIVACY_MODEL_ID", "fastino/gliner2-privacy-filter-PII-multi")
    entity_types: list[str] = field(
        default_factory=lambda: [
            x.strip()
            for x in os.getenv(
                "PRIVACY_ENTITY_TYPES",
                "person,full_name,first_name,last_name,date_of_birth,email,phone_number,address,street_address,city,state_or_region,postal_code,country,government_id,national_id_number,passport_number,drivers_license_number,tax_id,bank_account,account_number,iban,payment_card,card_number,username,ip_address,password,api_key,access_token,secret",
            ).split(",")
            if x.strip()
        ]
    )
    device: str = os.getenv("DEVICE", "auto")
    torch_dtype: str = os.getenv("TORCH_DTYPE", "auto")
    filter_output: bool = os.getenv("FILTER_OUTPUT", "true").lower() in {"1", "true", "yes", "on"}
    min_entity_score: float = float(os.getenv("MIN_ENTITY_SCORE", "0.50"))
    max_string_chars: int = int(os.getenv("MAX_STRING_CHARS", "200000"))
    model_idle_unload_seconds: int = int(os.getenv("MODEL_IDLE_UNLOAD_SECONDS", "300"))
    model_suffix: str = os.getenv("MODEL_SUFFIX", "-anonym")
    skip_json_keys: set[str] = field(
        default_factory=lambda: {
            x.strip()
            for x in os.getenv(
                "SKIP_JSON_KEYS",
                "model,role,type,stream,temperature,max_tokens,top_p,tools,tool_choice,name,thinking,reasoning,reasoning_effort",
            ).split(",")
            if x.strip()
        }
    )
    metrics_require_auth: bool = os.getenv("METRICS_REQUIRE_AUTH", "true").lower() in {"1", "true", "yes", "on"}


settings = Settings()


def suffix_model_id(model_id: str) -> str:
    if not model_id or not settings.model_suffix or model_id.endswith(settings.model_suffix):
        return model_id
    return f"{model_id}{settings.model_suffix}"


def unsuffix_model_id(model_id: str) -> str:
    suffix = settings.model_suffix
    if suffix and model_id.endswith(suffix) and len(model_id) > len(suffix):
        return model_id[: -len(suffix)]
    return model_id


def unsuffix_model_path(full_path: str) -> str:
    parts = full_path.split("/")
    if len(parts) >= 2 and parts[0] == "models":
        parts[1] = unsuffix_model_id(parts[1])
    return "/".join(parts)


def rewrite_request_model_ids(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    out = dict(value)
    model_id = out.get("model")
    if isinstance(model_id, str):
        model_id = model_id.strip()
        if not model_id or model_id == settings.model_suffix:
            raise HTTPException(status_code=400, detail="invalid_model_id")
        out["model"] = unsuffix_model_id(model_id)
    return out


def rewrite_response_model_ids(value: Any, *, models_endpoint: bool = False) -> Any:
    if isinstance(value, list):
        return [rewrite_response_model_ids(item, models_endpoint=models_endpoint) for item in value]
    if not isinstance(value, dict):
        return value
    out = dict(value)
    model_id = out.get("model")
    if isinstance(model_id, str):
        out["model"] = suffix_model_id(model_id)
    if models_endpoint:
        object_id = out.get("id")
        if isinstance(object_id, str) and out.get("object") == "model":
            out["id"] = suffix_model_id(object_id)
    data = out.get("data")
    if isinstance(data, list):
        out["data"] = [rewrite_response_model_ids(item, models_endpoint=True) for item in data]
    return out


class GlobalMetrics:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.requests_total = 0
        self.filtered_requests_total = 0
        self.filtered_tokens_total = 0
        self.filtered_spans_total = 0
        self.filtered_by_label: dict[str, int] = {}

    async def add(self, tokens: int, spans: int, labels: dict[str, int], *, count_request: bool = True) -> None:
        async with self.lock:
            if count_request:
                self.requests_total += 1
            if tokens > 0 or spans > 0:
                self.filtered_requests_total += 1
            self.filtered_tokens_total += tokens
            self.filtered_spans_total += spans
            for key, value in labels.items():
                self.filtered_by_label[key] = self.filtered_by_label.get(key, 0) + value

    async def prometheus(self) -> str:
        async with self.lock:
            lines = [
                "# HELP privacy_proxy_requests_total Total proxied requests.",
                "# TYPE privacy_proxy_requests_total counter",
                f"privacy_proxy_requests_total {self.requests_total}",
                "# HELP privacy_proxy_filtered_requests_total Requests where at least one span was filtered.",
                "# TYPE privacy_proxy_filtered_requests_total counter",
                f"privacy_proxy_filtered_requests_total {self.filtered_requests_total}",
                "# HELP privacy_proxy_filtered_tokens_total Estimated number of tokens filtered.",
                "# TYPE privacy_proxy_filtered_tokens_total counter",
                f"privacy_proxy_filtered_tokens_total {self.filtered_tokens_total}",
                "# HELP privacy_proxy_filtered_spans_total Number of PII spans filtered.",
                "# TYPE privacy_proxy_filtered_spans_total counter",
                f"privacy_proxy_filtered_spans_total {self.filtered_spans_total}",
            ]
            for label, count in sorted(self.filtered_by_label.items()):
                safe = label.replace('"', '\\"')
                lines.append(f'privacy_proxy_filtered_spans_by_label_total{{label="{safe}"}} {count}')
            return "\n".join(lines) + "\n"


metrics = GlobalMetrics()


@dataclass
class RedactionStats:
    tokens: int = 0
    spans: int = 0
    labels: dict[str, int] = field(default_factory=dict)

    def add(self, label: str, token_count: int) -> None:
        self.tokens += token_count
        self.spans += 1
        self.labels[label] = self.labels.get(label, 0) + 1


class RedactionContext:
    def __init__(self) -> None:
        self.by_value: dict[tuple[str, str], str] = {}
        self.next_index: dict[str, int] = {}

    def placeholder(self, label: str, value: str) -> str:
        label = normalize_label(label)
        key = (label, value)
        if key in self.by_value:
            return self.by_value[key]
        self.next_index[label] = self.next_index.get(label, 0) + 1
        placeholder = f"[{label.upper()}_{self.next_index[label]}]"
        self.by_value[key] = placeholder
        return placeholder


def normalize_label(label: str) -> str:
    label = label or "private"
    label = label.replace("B-", "").replace("I-", "").replace("E-", "").replace("S-", "")
    return label.lower()


class PrivacySanitizer:
    def __init__(self) -> None:
        self.model = None
        self._last_used_at = 0.0
        self._load_lock = asyncio.Lock()

    def _touch(self) -> None:
        self._last_used_at = time.monotonic()

    def unload_if_idle(self) -> None:
        if self.model is None:
            return
        timeout = settings.model_idle_unload_seconds
        if timeout <= 0:
            return
        idle_for = time.monotonic() - self._last_used_at
        if idle_for < timeout:
            return
        log.info("Unloading privacy model after %.1fs of inactivity", idle_for)
        self.model = None
        gc.collect()

    async def ensure_loaded(self) -> None:
        self.unload_if_idle()
        if self.model is not None:
            return
        async with self._load_lock:
            if self.model is not None:
                return
            log.info("Loading privacy model: %s", settings.privacy_model_id)
            from gliner2 import GLiNER2

            self.model = GLiNER2.from_pretrained(settings.privacy_model_id)
            self._touch()
            log.info("Privacy model loaded")

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split())) if text else 0

    async def sanitize_text(self, text: str, ctx: RedactionContext, stats: RedactionStats) -> str:
        if not text or len(text) > settings.max_string_chars:
            return text
        await self.ensure_loaded()
        self._touch()
        try:
            result = self.model.extract_entities(
                text,
                settings.entity_types,
                threshold=settings.min_entity_score,
                include_confidence=True,
                include_spans=True,
            )
        except TypeError:
            result = self.model.extract_entities(text, settings.entity_types)
        except Exception as exc:
            log.exception("Privacy model inference failed")
            raise HTTPException(status_code=500, detail=f"privacy_filter_failed: {exc}") from exc
        spans = self._spans_from_result(text, result)
        if not spans:
            return text
        spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        merged: list[tuple[int, int, str]] = []
        for start, end, label in spans:
            if not merged or start >= merged[-1][1]:
                merged.append((start, end, label))
            elif end > merged[-1][1]:
                prev_start, _prev_end, prev_label = merged[-1]
                merged[-1] = (prev_start, end, prev_label)
        out: list[str] = []
        last = 0
        for start, end, label in merged:
            original = text[start:end]
            out.append(text[last:start])
            out.append(ctx.placeholder(label, original))
            last = end
            stats.add(label, self.count_tokens(original))
        out.append(text[last:])
        return "".join(out)

    def _spans_from_result(self, text: str, result: Any) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str]] = []
        if isinstance(result, list):
            iterable = result
        elif isinstance(result, dict):
            entities = result.get("entities", result)
            iterable = []
            if isinstance(entities, dict):
                for label, values in entities.items():
                    if isinstance(values, list):
                        iterable.extend({"label": label, "text": value} if isinstance(value, str) else {"label": label, **value} for value in values)
            elif isinstance(entities, list):
                iterable = entities
        else:
            iterable = []
        for entity in iterable:
            if not isinstance(entity, dict):
                continue
            score = float(entity.get("score", entity.get("confidence", 1.0)) or 0.0)
            if score < settings.min_entity_score:
                continue
            start = entity.get("start")
            end = entity.get("end")
            value = entity.get("text") or entity.get("value") or entity.get("word")
            label = entity.get("label") or entity.get("entity_group") or entity.get("entity") or "private"
            if not isinstance(start, int) or not isinstance(end, int):
                if not value:
                    continue
                index = text.find(str(value))
                if index < 0:
                    continue
                start, end = index, index + len(str(value))
            if start < 0 or end <= start or end > len(text):
                continue
            spans.append((start, end, normalize_label(str(label))))
        return spans

    async def sanitize_payload(self, payload: Any) -> tuple[Any, RedactionStats]:
        ctx = RedactionContext()
        stats = RedactionStats()
        sanitized = await self._sanitize_any(payload, ctx, stats, parent_key=None)
        return sanitized, stats

    async def _sanitize_any(self, value: Any, ctx: RedactionContext, stats: RedactionStats, parent_key: str | None) -> Any:
        if parent_key in settings.skip_json_keys:
            return value
        if isinstance(value, str):
            return await self.sanitize_text(value, ctx, stats)
        if isinstance(value, list):
            return [await self._sanitize_any(item, ctx, stats, parent_key=None) for item in value]
        if isinstance(value, dict):
            return {key: await self._sanitize_any(item, ctx, stats, parent_key=str(key)) for key, item in value.items()}
        return value


sanitizer = PrivacySanitizer()
app = FastAPI(title="OpenAI Privacy Filter Proxy GLiNER2", version="1.0.0")


def extract_bearer(req: Request) -> str:
    auth = req.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return ""
    return auth.split(" ", 1)[1].strip()


def require_auth(req: Request, *, metrics_auth: bool = False) -> None:
    if metrics_auth and not settings.metrics_require_auth:
        return
    if not settings.inbound_api_keys:
        return
    if extract_bearer(req) not in settings.inbound_api_keys:
        raise HTTPException(status_code=401, detail="invalid_or_missing_api_token")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": settings.privacy_model_id,
        "upstream": settings.upstream_base_url,
        "filter_output": settings.filter_output,
        "model_suffix": settings.model_suffix,
    }


@app.get("/metrics")
async def get_metrics(req: Request) -> PlainTextResponse:
    require_auth(req, metrics_auth=True)
    return PlainTextResponse(await metrics.prometheus(), media_type="text/plain")


def build_upstream_headers(req: Request) -> dict[str, str]:
    excluded = {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
    headers = {key: value for key, value in req.headers.items() if key.lower() not in excluded}
    if settings.upstream_api_key:
        headers["authorization"] = f"Bearer {settings.upstream_api_key}"
    headers["content-type"] = "application/json"
    return headers


def headers_for_modified_body(resp: Response) -> dict[str, str]:
    excluded = {"content-length", "content-encoding", "transfer-encoding", "connection"}
    return {key: value for key, value in resp.headers.items() if key.lower() not in excluded}


def response_models_endpoint(full_path: str) -> bool:
    return full_path == "models" or full_path.startswith("models/")


def add_response_model_suffixes(upstream_resp: Response, full_path: str) -> Response:
    content_type = upstream_resp.headers.get("content-type", "")
    if "application/json" not in content_type:
        return upstream_resp
    try:
        response_payload = json.loads(upstream_resp.body)
    except Exception:
        return upstream_resp
    response_payload = rewrite_response_model_ids(response_payload, models_endpoint=response_models_endpoint(full_path))
    return JSONResponse(content=response_payload, status_code=upstream_resp.status_code, headers=headers_for_modified_body(upstream_resp))


async def forward_request(req: Request, full_path: str, sanitized_payload: Any, stream: bool = False) -> Response:
    full_path = unsuffix_model_path(full_path)
    url = f"{settings.upstream_base_url}/{full_path}"
    timeout = httpx.Timeout(600.0, connect=30.0)
    if stream:
        client = httpx.AsyncClient(timeout=timeout)
        upstream_req = client.build_request(
            method=req.method,
            url=url,
            headers=build_upstream_headers(req),
            params=dict(req.query_params),
            json=sanitized_payload,
        )
        upstream_stream = await client.send(upstream_req, stream=True)

        async def close_upstream() -> None:
            await upstream_stream.aclose()
            await client.aclose()

        headers = {key: value for key, value in upstream_stream.headers.items() if key.lower() not in {"content-length", "connection"}}
        return StreamingResponse(
            upstream_stream.aiter_bytes(),
            status_code=upstream_stream.status_code,
            headers=headers,
            media_type=upstream_stream.headers.get("content-type", "application/json"),
            background=BackgroundTask(close_upstream),
        )
    async with httpx.AsyncClient(timeout=timeout) as client:
        upstream = await client.request(
            method=req.method,
            url=url,
            headers=build_upstream_headers(req),
            params=dict(req.query_params),
            json=sanitized_payload,
        )
    headers = {key: value for key, value in upstream.headers.items() if key.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=headers, media_type=upstream.headers.get("content-type", "application/json"))


@app.api_route("/v1/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_openai(req: Request, full_path: str) -> Response:
    if req.method == "OPTIONS":
        return Response(status_code=204)
    require_auth(req)
    if req.method in {"GET", "DELETE"}:
        upstream_resp = await forward_request(req, full_path, sanitized_payload=None)
        return add_response_model_suffixes(upstream_resp, full_path)
    try:
        payload = await req.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="expected_json_body") from exc
    start = time.perf_counter()
    sanitized_payload, in_stats = await sanitizer.sanitize_payload(payload)
    sanitized_payload = rewrite_request_model_ids(sanitized_payload)
    await metrics.add(in_stats.tokens, in_stats.spans, in_stats.labels)
    wants_stream = bool(isinstance(payload, dict) and payload.get("stream") is True)
    if wants_stream:
        return await forward_request(req, full_path, sanitized_payload, stream=True)
    upstream_resp = await forward_request(req, full_path, sanitized_payload, stream=False)
    upstream_resp.headers["x-privacy-filtered-tokens"] = str(in_stats.tokens)
    upstream_resp.headers["x-privacy-filtered-spans"] = str(in_stats.spans)
    upstream_resp.headers["x-privacy-filter-latency-ms"] = str(round((time.perf_counter() - start) * 1000, 2))
    rewritten_resp = add_response_model_suffixes(upstream_resp, full_path)
    content_type = rewritten_resp.headers.get("content-type", "")
    if "application/json" not in content_type:
        return rewritten_resp
    try:
        response_payload = json.loads(rewritten_resp.body)
    except Exception:
        return rewritten_resp
    out_stats = RedactionStats()
    if settings.filter_output:
        response_payload, out_stats = await sanitizer.sanitize_payload(response_payload)
        await metrics.add(out_stats.tokens, out_stats.spans, out_stats.labels, count_request=False)
    final = JSONResponse(content=response_payload, status_code=rewritten_resp.status_code, headers=headers_for_modified_body(rewritten_resp))
    if settings.filter_output:
        final.headers["x-privacy-filtered-output-tokens"] = str(out_stats.tokens)
        final.headers["x-privacy-filtered-output-spans"] = str(out_stats.spans)
    return final


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=settings.host, port=settings.port, log_level=os.getenv("LOG_LEVEL", "info"))
