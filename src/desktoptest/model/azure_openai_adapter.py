"""
model/azure_openai_adapter.py — Azure OpenAI backend (o4-mini, gpt-4o, ...).

This is the WORKING adapter. It mirrors the pattern from your Playwright
studio's services/llm.py: an openai.AzureOpenAI client, deployment-name as the
"model", text + vision content blocks.

Note on o4-mini (reasoning models): they reject `temperature` and use
`max_completion_tokens` instead of `max_tokens`. The adapter detects this and
adjusts the request, so the same code path serves both gpt-4o and o4-mini.
"""

from __future__ import annotations

import os
from typing import Optional

from .base import ModelAdapter, ModelConfig, ModelError


def _is_reasoning_deployment(name: str) -> bool:
    n = (name or "").lower()
    return n.startswith("o1") or n.startswith("o3") or n.startswith("o4")


class AzureOpenAIAdapter(ModelAdapter):
    def __init__(self, cfg: ModelConfig):
        super().__init__(cfg)
        try:
            from openai import AzureOpenAI
        except ImportError as e:  # pragma: no cover
            raise ModelError("openai package not installed (pip install openai)") from e

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if not endpoint or not api_key:
            raise ModelError(
                "AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY not set "
                "(see .env.example)"
            )
        self._client = AzureOpenAI(
            api_key=api_key,
            api_version=cfg.api_version or "2024-02-01",
            azure_endpoint=endpoint,
            timeout=cfg.timeout,
        )
        self._reasoning = _is_reasoning_deployment(cfg.deployment)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _token_kwargs(self, max_tokens: int) -> dict:
        # Reasoning models use max_completion_tokens; classic models use max_tokens.
        key = "max_completion_tokens" if self._reasoning else "max_tokens"
        return {key: max_tokens}

    def _temp_kwargs(self, temperature: float) -> dict:
        # Reasoning models reject an explicit temperature.
        return {} if self._reasoning else {"temperature": temperature}

    def _create(self, messages, max_tokens, temperature):
        try:
            resp = self._client.chat.completions.create(
                model=self.cfg.deployment,
                messages=messages,
                **self._token_kwargs(max_tokens),
                **self._temp_kwargs(temperature),
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 — normalise for the retry layer
            raise ModelError(str(e)) from e

    # ── interface ────────────────────────────────────────────────────────────
    def complete(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        return self._create(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            max_tokens or self.cfg.max_tokens,
            self.cfg.temperature if temperature is None else temperature,
        )

    def complete_vision(self, system: str, user: str, image_b64: str,
                        max_tokens: Optional[int] = None,
                        temperature: Optional[float] = None) -> str:
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": f"{system}\n\n{user}"},
            ],
        }]
        return self._create(
            messages,
            max_tokens or self.cfg.max_tokens,
            self.cfg.temperature if temperature is None else temperature,
        )
