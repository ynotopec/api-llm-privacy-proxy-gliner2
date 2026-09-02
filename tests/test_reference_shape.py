import ast
from pathlib import Path

SOURCE = Path("app.py").read_text()


def test_openai_v1_route_matches_reference_shape():
    assert '@app.api_route("/v1/{full_path:path}"' in SOURCE
    assert 'async def proxy_openai(req: Request, full_path: str)' in SOURCE


def test_reference_auth_and_model_variables_are_supported():
    settings_source = Path("privacy_proxy_core/settings.py").read_text()
    assert 'INBOUND_API_KEYS' in settings_source
    assert 'PRIVACY_MODEL_ID' in settings_source
    assert 'PRIVACY_ENTITY_TYPES' in SOURCE
    assert 'fastino/gliner2-privacy-filter-PII-multi' in settings_source


def test_reference_features_are_present():
    assert '@app.get("/metrics")' in SOURCE
    settings_source = Path("privacy_proxy_core/settings.py").read_text()
    assert 'MODEL_SUFFIX' in settings_source
    assert 'FILTER_OUTPUT' in settings_source


def test_gliner2_extract_entities_receives_entity_types():
    sanitizer_source = Path("privacy_proxy_core/sanitizers/gliner2.py").read_text()
    assert 'extract_entities(\n                text,\n                self.entity_types,' in sanitizer_source
    assert 'extract_entities(text, self.entity_types)' in sanitizer_source


def test_health_exposes_device_revision_marker():
    assert 'APP_REVISION = "core-integration"' in SOURCE
    assert '"revision": APP_REVISION' in SOURCE
    assert '"resolved_device": sanitizer.model_device' in SOURCE
    assert '"cuda_available": sanitizer.cuda_available' in SOURCE


def test_model_idle_unload_runs_in_background_and_clears_memory():
    assert 'MODEL_IDLE_CHECK_SECONDS' in SOURCE
    sanitizer_source = Path("privacy_proxy_core/sanitizers/gliner2.py").read_text()
    assert 'asyncio.create_task(_watch(), name="gliner2-idle")' in sanitizer_source
    assert 'torch.cuda.empty_cache()' in sanitizer_source
    assert 'await sanitizer.start_idle_watcher()' in SOURCE
    assert 'await sanitizer.stop_idle_watcher()' in SOURCE


def test_llm_can_be_disabled_for_sanitize_only_mode():
    assert 'LLM_ENABLED' in Path("privacy_proxy_core/settings.py").read_text()
    assert '"llm_enabled": settings.llm_enabled' in SOURCE
    assert '"object": "privacy_proxy.sanitized_payload"' in SOURCE
    assert '"object": "chat.completion"' in SOURCE
    assert '"choices"' in SOURCE
    assert 'sanitized_chat_content(sanitized_payload)' in SOURCE
    assert 'raise HTTPException(status_code=503, detail="llm_disabled")' in SOURCE


def test_python_sources_parse():
    for path in Path("privacy_proxy_core").rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
    ast.parse(SOURCE, filename="app.py")
