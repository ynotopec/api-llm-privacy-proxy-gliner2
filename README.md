# api-llm-privacy-proxy-gliner2

OpenAI-compatible HTTP proxy that redacts personally identifiable information before forwarding requests to an upstream LLM API. It uses [`fastino/gliner2-privacy-filter-PII-multi`](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi), a multilingual GLiNER2 PII model for 42 PII labels.

## Features

- Drop-in proxy for OpenAI-compatible endpoints such as `/chat/completions` and `/responses`.
- Redacts text in chat `messages[].content` and top-level `input` fields.
- Supports plain text message content and multimodal text parts.
- Configurable upstream API base URL, API key, GLiNER2 model, labels, and threshold.
- Docker-ready FastAPI service.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `UPSTREAM_API_KEY` | unset | API key sent to the upstream LLM provider. `OPENAI_API_KEY` is also accepted. |
| `UPSTREAM_BASE_URL` | `https://api.openai.com/v1` | Upstream OpenAI-compatible API base URL. |
| `GLINER2_MODEL` | `fastino/gliner2-privacy-filter-PII-multi` | Hugging Face model ID loaded by GLiNER2. |
| `PII_THRESHOLD` | `0.5` | Detection threshold passed to `extract_entities`. |
| `PII_LABELS` | all supported labels | Comma-separated label allow-list for detection. |

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export UPSTREAM_API_KEY="sk-..."
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then point OpenAI-compatible clients to `http://localhost:8000` instead of the upstream provider:

```bash
curl http://localhost:8000/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Email john.smith@example.com about the contract."}]
  }'
```

## Docker

```bash
docker build -t api-llm-privacy-proxy-gliner2 .
docker run --rm -p 8000:8000 \
  -e UPSTREAM_API_KEY="sk-..." \
  api-llm-privacy-proxy-gliner2
```

## Health check

```bash
curl http://localhost:8000/health
```
