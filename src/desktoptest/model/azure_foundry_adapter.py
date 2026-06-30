"""
model/azure_foundry_adapter.py — Azure AI Foundry backend (Claude Haiku). STUB.

WHY THIS IS SEPARATE FROM THE OPENAI ADAPTER
--------------------------------------------
Haiku (Anthropic) on Azure is served through Azure AI Foundry. The openai SDK
used by AzureOpenAIAdapter CANNOT talk to Foundry endpoints — it speaks only the
Azure OpenAI protocol. So Haiku needs its own transport. Two ways to fill this in:

  1. Azure AI Inference SDK (recommended, native Azure):
         pip install azure-ai-inference azure-core
         from azure.ai.inference import ChatCompletionsClient
         from azure.core.credentials import AzureKeyCredential
         client = ChatCompletionsClient(endpoint=..., credential=AzureKeyCredential(key))
         resp = client.complete(messages=[...], model=deployment, ...)

  2. LiteLLM gateway: route "azure_ai/<deployment>" through litellm.completion(),
     keeping a single call signature across providers.

The interface below already matches ModelAdapter, so once you implement the two
methods the engine picks Haiku up with zero changes elsewhere — just set
roles.verifier: haiku (or similar) in config/models.yaml.
"""

from __future__ import annotations

from typing import Optional

from .base import ModelAdapter, ModelConfig, ModelError

_STUB_MESSAGE = (
    "Azure Foundry (Haiku) adapter is stubbed. Implement complete()/complete_vision() "
    "using the Azure AI Inference SDK or LiteLLM, set AZURE_FOUNDRY_ENDPOINT / "
    "AZURE_FOUNDRY_API_KEY / AZURE_FOUNDRY_DEPLOYMENT, then route a role to 'haiku' "
    "in config/models.yaml. See the module docstring for the exact wiring."
)


class AzureFoundryAdapter(ModelAdapter):
    def __init__(self, cfg: ModelConfig):
        super().__init__(cfg)
        # Intentionally do NOT construct a client yet — keep the stub importable
        # so the rest of the system loads even before Foundry is provisioned.

    def complete(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        raise ModelError(_STUB_MESSAGE)

    def complete_vision(self, system: str, user: str, image_b64: str,
                        max_tokens: Optional[int] = None,
                        temperature: Optional[float] = None) -> str:
        raise ModelError(_STUB_MESSAGE)

    # ── reference implementation (commented) ─────────────────────────────────
    # def __init__(self, cfg):
    #     super().__init__(cfg)
    #     import os
    #     from azure.ai.inference import ChatCompletionsClient
    #     from azure.core.credentials import AzureKeyCredential
    #     self._client = ChatCompletionsClient(
    #         endpoint=os.environ["AZURE_FOUNDRY_ENDPOINT"],
    #         credential=AzureKeyCredential(os.environ["AZURE_FOUNDRY_API_KEY"]),
    #     )
    #
    # def complete(self, system, user, max_tokens=None, temperature=None):
    #     try:
    #         r = self._client.complete(
    #             model=self.cfg.deployment,
    #             messages=[{"role": "system", "content": system},
    #                       {"role": "user", "content": user}],
    #             max_tokens=max_tokens or self.cfg.max_tokens,
    #             temperature=self.cfg.temperature if temperature is None else temperature,
    #         )
    #         return r.choices[0].message.content or ""
    #     except Exception as e:
    #         raise ModelError(str(e)) from e
