from pathlib import Path

SOURCE = Path("app.py").read_text()


def test_openai_v1_route_matches_reference_shape():
    assert '@app.api_route("/v1/{full_path:path}"' in SOURCE
    assert 'async def proxy_openai(req: Request, full_path: str)' in SOURCE


def test_reference_auth_and_model_variables_are_supported():
    assert 'INBOUND_API_KEYS' in SOURCE
    assert 'PRIVACY_MODEL_ID' in SOURCE
    assert 'PRIVACY_ENTITY_TYPES' in SOURCE
    assert 'fastino/gliner2-privacy-filter-PII-multi' in SOURCE


def test_reference_features_are_present():
    assert '@app.get("/metrics")' in SOURCE
    assert 'MODEL_SUFFIX' in SOURCE
    assert 'FILTER_OUTPUT' in SOURCE


def test_gliner2_extract_entities_receives_entity_types():
    assert 'extract_entities(\n                text,\n                settings.entity_types,' in SOURCE
    assert 'extract_entities(text, settings.entity_types)' in SOURCE


def test_health_exposes_entity_types_revision_marker():
    assert 'APP_REVISION = "gliner2-entity-types"' in SOURCE
    assert '"revision": APP_REVISION' in SOURCE
