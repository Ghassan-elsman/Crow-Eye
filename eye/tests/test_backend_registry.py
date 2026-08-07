"""
The backend catalogue and configs/eye_config_schema.json must never drift apart.

This is the regression guard for the class of bug where the provider list grew to
17 backends while the schema's `backend` enum still allowed 8. Nothing failed
loudly: connectivity validated, then `save_config` raised a ValidationError that
the wizard reported as "Failed to save configuration" and the bridge swallowed as
a log line — so a model switch worked for the session and silently reverted on
restart.

Every id the ModelRouter can route MUST validate against the schema, in a config
shaped the way the wizard / bridge actually writes it.
"""

import json
import unittest
from pathlib import Path

import jsonschema

from eye.backends.backend_registry import (
    CLOUD_API_BACKENDS,
    INTEGRATION_TYPES,
    LOCAL_CLI_BACKENDS,
    LOCAL_SERVER_BACKENDS,
    SUPPORTED_BACKENDS,
    integration_type_for,
)
from eye.backends.local_cli.cli_profiles import CLI_PROFILES

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "configs" / "eye_config_schema.json"


def _schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _config_for(backend: str) -> dict:
    """A minimal config for `backend`, shaped the way the app writes it."""
    it = integration_type_for(backend)
    cfg = {"integration_type": it, "backend": backend, "model_name": "some-model"}
    if it == "local_cli":
        cfg["executable_path"] = "/usr/local/bin/agent"
    if backend in ("lm_studio", "vllm"):
        cfg["api_endpoint"] = "http://localhost:1234"
    return cfg


class TestRegistrySchemaSync(unittest.TestCase):
    def setUp(self):
        self.schema = _schema()

    def test_every_supported_backend_validates(self):
        for backend in SUPPORTED_BACKENDS:
            with self.subTest(backend=backend):
                jsonschema.validate(_config_for(backend), self.schema)

    def test_schema_enum_matches_registry(self):
        self.assertEqual(
            sorted(self.schema["properties"]["backend"]["enum"]),
            sorted(SUPPORTED_BACKENDS),
            "configs/eye_config_schema.json backend enum has drifted from "
            "eye.backends.backend_registry.SUPPORTED_BACKENDS",
        )

    def test_integration_type_enum_matches_registry(self):
        self.assertEqual(
            sorted(self.schema["properties"]["integration_type"]["enum"]),
            sorted(INTEGRATION_TYPES),
        )

    def test_every_cli_profile_is_a_valid_backend(self):
        # A profile the wizard offers but the schema rejects is unsettable.
        for profile_id in CLI_PROFILES:
            with self.subTest(profile=profile_id):
                self.assertIn(profile_id, LOCAL_CLI_BACKENDS)
                jsonschema.validate(_config_for(profile_id), self.schema)

    def test_local_server_spelling_and_legacy_alias_both_accepted(self):
        # 'local_server' is what the router/bridge write; 'local_api' is what
        # older builds wrote. Rejecting either breaks persistence.
        for it in ("local_server", "local_api"):
            with self.subTest(integration_type=it):
                jsonschema.validate(
                    {"integration_type": it, "backend": "lm_studio",
                     "model_name": "m", "api_endpoint": "http://localhost:1234"},
                    self.schema,
                )

    def test_ollama_does_not_require_an_endpoint(self):
        # OllamaBackend defaults to http://localhost:11434, so requiring
        # api_endpoint here would reject the "Connect to Ollama…" config.
        jsonschema.validate(
            {"integration_type": "local_server", "backend": "ollama", "model_name": "llama3"},
            self.schema,
        )

    def test_lm_studio_still_requires_an_endpoint(self):
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(
                {"integration_type": "local_server", "backend": "lm_studio", "model_name": "m"},
                self.schema,
            )


class TestRegistryRouting(unittest.TestCase):
    def test_integration_type_for_each_group(self):
        for backend in LOCAL_CLI_BACKENDS:
            self.assertEqual(integration_type_for(backend), "local_cli", backend)
        for backend in LOCAL_SERVER_BACKENDS:
            self.assertEqual(integration_type_for(backend), "local_server", backend)
        for backend in CLOUD_API_BACKENDS:
            self.assertEqual(integration_type_for(backend), "cloud_api", backend)

    def test_router_routes_every_registered_backend(self):
        """Every id in the registry must reach a real backend branch — no id may
        fall through to 'Unsupported forensic AI backend'."""
        from eye.services.model_router import ModelRouter

        class _FakeCredentials:
            def get_credential(self, key, timeout=2.0):
                return "test-key"

        for backend in SUPPORTED_BACKENDS:
            with self.subTest(backend=backend):
                cfg = _config_for(backend)
                router = ModelRouter(cfg, _FakeCredentials())
                self.assertIsNotNone(router.backend)

    def test_no_backend_id_is_offered_but_unroutable(self):
        # Guards the inverse drift: an id added to the schema/wizard but never
        # wired into ModelRouter._initialize_backend.
        self.assertEqual(
            set(SUPPORTED_BACKENDS),
            set(LOCAL_CLI_BACKENDS) | set(LOCAL_SERVER_BACKENDS) | set(CLOUD_API_BACKENDS),
        )


if __name__ == "__main__":
    unittest.main()
