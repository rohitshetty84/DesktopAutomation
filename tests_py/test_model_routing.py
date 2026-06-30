"""
Model-layer routing tests — config parsing + role->provider resolution.
No network: we stub the adapter factory so no real Azure client is built.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from desktoptest.model import LLMService  # noqa: E402
from desktoptest.model import service as svc_mod  # noqa: E402
from desktoptest.model.base import ModelAdapter  # noqa: E402

CONFIG = str(Path(__file__).resolve().parents[1] / "config" / "models.yaml")


class StubAdapter(ModelAdapter):
    def complete(self, system, user, max_tokens=None, temperature=None):
        return f"text:{self.cfg.name}:{self.cfg.deployment}"

    def complete_vision(self, system, user, image_b64, max_tokens=None, temperature=None):
        return f"vision:{self.cfg.name}"


def _patch(monkeypatch):
    monkeypatch.setattr(svc_mod, "_build_adapter", lambda cfg: StubAdapter(cfg))


def test_roles_resolve_to_models(monkeypatch):
    os.environ["AZURE_OPENAI_DEPLOYMENT"] = "gpt-4o"
    os.environ["AZURE_OPENAI_API_VERSION"] = "2024-02-01"
    os.environ["AZURE_REASONING_DEPLOYMENT"] = "o4-mini"
    os.environ["AZURE_REASONING_API_VERSION"] = "2024-12-01-preview"
    _patch(monkeypatch)

    llm = LLMService.from_config(CONFIG)
    # planner -> reasoning -> o4-mini ; verifier -> general -> gpt-4o
    assert llm.ask("planner", "s", "u").endswith("o4-mini")
    assert llm.ask("verifier", "s", "u").endswith("gpt-4o")


def test_missing_deployment_raises(monkeypatch):
    # Both reasoning (primary) AND general (fallback) lack a deployment, so the
    # fallback can't mask it and the ModelError propagates.
    os.environ.pop("AZURE_REASONING_DEPLOYMENT", None)
    os.environ.pop("AZURE_OPENAI_DEPLOYMENT", None)
    _patch(monkeypatch)
    llm = LLMService.from_config(CONFIG)
    try:
        llm.ask("planner", "s", "u")
        assert False, "expected ModelError"
    except Exception as e:
        assert "deployment" in str(e).lower()


def test_fallback_masks_primary_failure(monkeypatch):
    # reasoning has no deployment but general does -> fallback should answer.
    os.environ.pop("AZURE_REASONING_DEPLOYMENT", None)
    os.environ["AZURE_OPENAI_DEPLOYMENT"] = "gpt-4o"
    _patch(monkeypatch)
    llm = LLMService.from_config(CONFIG)
    assert llm.ask("planner", "s", "u").endswith("gpt-4o")
