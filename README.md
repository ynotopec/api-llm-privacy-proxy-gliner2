# api-llm-privacy-proxy-gliner2

Minimal OpenAI-compatible privacy proxy using `fastino/gliner2-privacy-filter-PII-multi`.

## Start

```bash
cp .env.example .env
# edit .env: set UPSTREAM_API_KEY and PROXY_API_TOKEN
./run.sh 0.0.0.0 8000
```

Use the most common OpenAI-compatible client base URL shape:

```text
http://127.0.0.1:8000/v1
```

The proxy accepts `/v1/...` routes and forwards them to the upstream base URL without duplicating `/v1`. Send the proxy token to this service as the client `Authorization: Bearer ...` token. The proxy replaces it with `UPSTREAM_API_KEY` when forwarding upstream.

## Important variables

```bash
UPSTREAM_API_KEY=sk-...
PROXY_API_TOKEN=your-proxy-token
#UPSTREAM_BASE_URL=https://api.openai.com/v1
#GLINER2_MODEL=fastino/gliner2-privacy-filter-PII-multi
#PII_THRESHOLD=0.5
#CUDA_VISIBLE_DEVICES=0
```

## Install layout

`run.sh` auto-runs the idempotent, upgrade-compatible `install.sh` when the virtualenv is missing. `install.sh` uses `uv` and installs into:

```text
~/venv/api-llm-privacy-proxy-gliner2
```

Run `./install.sh` again to upgrade dependencies/code in the same virtualenv. Set `AUTO_INSTALL=0` if `run.sh` should fail instead of installing automatically.

## systemd example

```ini
[Service]
WorkingDirectory=/opt/api-llm-privacy-proxy-gliner2
ExecStart=/bin/bash -lc 'source /opt/api-llm-privacy-proxy-gliner2/run.sh 0.0.0.0 8000'
Restart=always
```

## API

The proxy forwards popular OpenAI-compatible routes such as:

- `/v1/chat/completions`
- `/v1/responses`
- `/v1/embeddings`
- `/v1/completions`

Text in chat `messages[].content`, multimodal text parts, and top-level `input` is redacted before forwarding.

## GPU hosts

The runner sets safe CUDA defaults for NVIDIA H100 / DGX Spark class hosts and can be overridden in `.env`.
