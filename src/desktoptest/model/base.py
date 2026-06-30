"""
model/base.py — provider-agnostic adapter interface.

Every backend (Azure OpenAI, Azure AI Foundry/Haiku, ...) implements
`ModelAdapter`. The rest of the system only ever sees this interface, so a
model swap is a config change, not a code change.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelConfig:
    """Resolved configuration for one logical model."""
    name: str                       # logical key, e.g. "reasoning"
    provider: str                   # "azure_openai" | "azure_foundry"
    deployment: str                 # Azure deployment name (NOT model name)
    api_version: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1500


class ModelAdapter(abc.ABC):
    """Text-in/text-out and image+text-in/text-out, normalised across providers."""

    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg

    @abc.abstractmethod
    def complete(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        """Plain text chat completion."""
        raise NotImplementedError

    @abc.abstractmethod
    def complete_vision(self, system: str, user: str, image_b64: str,
                        max_tokens: Optional[int] = None,
                        temperature: Optional[float] = None) -> str:
        """Image + text chat completion. image_b64 is a base64 PNG (no data: prefix)."""
        raise NotImplementedError


class ModelError(RuntimeError):
    """Raised when a provider call fails after retries."""
