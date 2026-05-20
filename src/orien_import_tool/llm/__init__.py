"""Pluggable LLM clients.

The proposers (:class:`~orien_import_tool.mapping.LLMProposer`,
:class:`~orien_import_tool.aliases.LLMAliasMiner`) accept any client that
satisfies :class:`ProposerClient` — a minimal Protocol covering the single
method they actually call. This lets the same proposer code drive:

* Anthropic's API (default, via the ``anthropic`` SDK)
* Any OpenAI-compatible endpoint — vLLM, Ollama (with the OpenAI-compat
  shim), LM Studio, llama-cpp-server, TGI, LocalAI, llamafile — via
  :class:`OpenAIProposerClient` pointed at the local ``base_url``
* A test fake (see ``tests/mapping/test_llm_proposer.py``)

Local-model usage::

    from orien_import_tool.llm import OpenAIProposerClient
    from orien_import_tool.mapping import LLMProposer

    client = OpenAIProposerClient(
        base_url="http://localhost:8000/v1",  # vLLM / LM Studio default
        model_name="qwen2.5-32b-instruct",    # whatever your server serves
    )
    proposer = LLMProposer(ref, client=client, model="qwen2.5-32b-instruct")
"""

from orien_import_tool.llm.openai_compat import OpenAIProposerClient
from orien_import_tool.llm.protocols import ParsedResponse, ProposerClient

__all__ = [
    "OpenAIProposerClient",
    "ParsedResponse",
    "ProposerClient",
]
