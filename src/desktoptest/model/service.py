"""
model/service.py — LLMService: config-driven, role-based model router.

Generalises the two-client router from your Playwright studio:
  * studio branched on DEPLOYMENT (main vs reasoning).
  * this branches on PROVIDER (azure_openai vs azure_foundry), so o4-mini and
    Haiku live behind the same interface.

Public surface stays tiny and stable:
    svc = LLMService.from_config("config/models.yaml")
    svc.ask("planner",  system, user)
    svc.ask("verifier", system, user)
    svc.vision("self_heal", system, user, image_b64)

Roles (planner / verifier / self_heal / fallback) map to logical models in YAML;
logical models map to a provider + Azure deployment. Transient errors retry with
backoff; a hard failure on the primary role falls back to the `fallback` role.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional

import yaml

from .base import ModelAdapter, ModelConfig, ModelError

logger = logging.getLogger("desktoptest.model")

_TRANSIENT = ("429", "rate limit", "timeout", "connection", "temporarily",
              "500", "502", "503", "504", "internal server error")


def _is_transient(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in _TRANSIENT)


def _build_adapter(cfg: ModelConfig) -> ModelAdapter:
    if cfg.provider == "azure_openai":
        from .azure_openai_adapter import AzureOpenAIAdapter
        return AzureOpenAIAdapter(cfg)
    if cfg.provider == "azure_foundry":
        from .azure_foundry_adapter import AzureFoundryAdapter
        return AzureFoundryAdapter(cfg)
    raise ModelError(f"Unknown provider: {cfg.provider!r}")


class LLMService:
    def __init__(self, roles: Dict[str, str], models: Dict[str, ModelConfig],
                 retry_attempts: int = 2, base_backoff: float = 1.5):
        self.roles = roles
        self.models = models
        self.retry_attempts = retry_attempts
        self.base_backoff = base_backoff
        self._adapters: Dict[str, ModelAdapter] = {}  # lazy, per logical model

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def from_config(cls, path: str) -> "LLMService":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        models: Dict[str, ModelConfig] = {}
        for key, m in (data.get("models") or {}).items():
            deployment = os.getenv(m.get("deployment_env", ""), "").strip()
            api_version = os.getenv(m.get("api_version_env", ""), "").strip() or None
            models[key] = ModelConfig(
                name=key,
                provider=m["provider"],
                deployment=deployment,
                api_version=api_version,
                temperature=float(m.get("temperature", 0.2)),
                max_tokens=int(m.get("max_tokens", 1500)),
                timeout=float(m.get("timeout", 120.0)),
            )
        retry = data.get("retry") or {}
        return cls(
            roles=data.get("roles") or {},
            models=models,
            retry_attempts=int(retry.get("attempts", 2)),
            base_backoff=float(retry.get("base_backoff", 1.5)),
        )

    # ── internals ────────────────────────────────────────────────────────────
    def _model_for_role(self, role: str) -> str:
        if role not in self.roles:
            raise ModelError(f"No model mapped for role {role!r} (check config roles:)")
        return self.roles[role]

    def _adapter(self, model_key: str) -> ModelAdapter:
        if model_key not in self._adapters:
            cfg = self.models.get(model_key)
            if cfg is None:
                raise ModelError(f"Unknown model key {model_key!r}")
            if not cfg.deployment:
                raise ModelError(
                    f"Model {model_key!r} has no deployment — is its *_env var set? "
                    f"(provider={cfg.provider})"
                )
            self._adapters[model_key] = _build_adapter(cfg)
        return self._adapters[model_key]

    def _call(self, model_key: str, fn_name: str, *args) -> str:
        last: Optional[Exception] = None
        for attempt in range(self.retry_attempts + 1):
            try:
                adapter = self._adapter(model_key)
                return getattr(adapter, fn_name)(*args)
            except ModelError as e:
                last = e
                if attempt < self.retry_attempts and _is_transient(str(e)):
                    backoff = self.base_backoff ** attempt
                    logger.warning("[%s] transient (%d/%d), backoff %.1fs: %s",
                                   model_key, attempt + 1, self.retry_attempts + 1,
                                   backoff, e)
                    time.sleep(backoff)
                    continue
                break
        raise last if last else ModelError("call failed without exception")

    def _with_fallback(self, role: str, fn_name: str, *args) -> str:
        primary = self._model_for_role(role)
        try:
            return self._call(primary, fn_name, *args)
        except ModelError as e:
            fb = self.roles.get("fallback")
            if not fb or fb == primary:
                raise
            logger.warning("[%s] primary model %s failed, falling back to %s: %s",
                           role, primary, fb, e)
            return self._call(fb, fn_name, *args)

    # ── public API ───────────────────────────────────────────────────────────
    def ask(self, role: str, system: str, user: str,
            max_tokens: Optional[int] = None,
            temperature: Optional[float] = None) -> str:
        return self._with_fallback(role, "complete", system, user, max_tokens, temperature)

    def vision(self, role: str, system: str, user: str, image_b64: str,
               max_tokens: Optional[int] = None,
               temperature: Optional[float] = None) -> str:
        return self._with_fallback(role, "complete_vision",
                                   system, user, image_b64, max_tokens, temperature)
