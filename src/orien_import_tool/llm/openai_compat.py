"""OpenAI-compatible client adapter for the LLM proposers.

Wraps the ``openai`` SDK pointed at any OpenAI-compatible endpoint — vLLM,
Ollama (OpenAI-compat shim), LM Studio, llama-cpp-server, TGI, LocalAI,
llamafile, hosted gateways. Exposes the surface the proposers expect
(``client.messages.parse(...)``) so they can swap in without code changes.

Two design choices that matter:

1. **JSON-schema enforcement**: the adapter calls
   ``client.chat.completions.parse(response_format=PydanticClass)``, which
   sends the Pydantic schema as ``response_format: json_schema``. Servers
   that support constrained decoding (vLLM grammar, Ollama format=json with
   structured output, llama.cpp grammars) enforce the schema on the server
   side. Servers that ignore it fall back to validation client-side via the
   SDK's parser — still works, just less reliable on small models.

2. **System-prompt flattening**: Anthropic's API takes ``system`` as a list
   of text blocks with optional ``cache_control``. OpenAI takes a single
   ``system`` role message. We concatenate the blocks; the ``cache_control``
   hints are lost (most local servers don't expose prompt caching anyway).
   If your runtime *does* offer prompt caching, configure it server-side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import openai
    from pydantic import BaseModel


@dataclass
class _ParseResult:
    """Tiny shim so the adapter's return value matches ``anthropic``'s."""

    parsed_output: Any


class _MessagesNamespace:
    """Bound to the parent client; exposes ``.parse(...)`` on it."""

    def __init__(self, parent: OpenAIProposerClient) -> None:
        self._parent = parent

    def parse(
        self,
        *,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[dict[str, Any]],
        output_format: type[BaseModel],
    ) -> _ParseResult:
        return self._parent._parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_format=output_format,
        )


class OpenAIProposerClient:
    """Adapter targeting any OpenAI-compatible chat-completions endpoint.

    ``base_url`` is required and should point at your runtime's
    ``/v1``-prefixed root (vLLM serves at ``http://host:8000/v1`` by default;
    Ollama's OpenAI shim at ``http://host:11434/v1``; LM Studio at
    ``http://localhost:1234/v1``).

    ``api_key`` is required by the OpenAI SDK contract; most local runtimes
    ignore it. Pass a dummy if your server doesn't authenticate.

    ``model_name`` is informational — the actual model used is whatever the
    proposer's ``model`` argument resolves to. We surface it here as a
    constructor hint for callers building configs.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "sk-local",
        timeout: float = 120.0,
        max_retries: int = 2,
        client: openai.OpenAI | None = None,
        model_name: str | None = None,
    ) -> None:
        self.model_name = model_name
        self._client = (
            client
            if client is not None
            else _build_openai_client(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                max_retries=max_retries,
            )
        )
        self.messages = _MessagesNamespace(self)

    # --- Internals -----------------------------------------------------------------

    def _parse(
        self,
        *,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[dict[str, Any]],
        output_format: type[BaseModel],
    ) -> _ParseResult:
        system_text = _flatten_system(system)
        openai_messages: list[dict[str, Any]] = []
        if system_text:
            openai_messages.append({"role": "system", "content": system_text})
        openai_messages.extend(messages)

        completion = self._client.chat.completions.parse(
            model=model,
            max_tokens=max_tokens,
            messages=openai_messages,
            response_format=output_format,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError(
                "OpenAI-compatible endpoint returned no parsed output for "
                f"schema {output_format.__name__}. "
                "The server may not support response_format=json_schema, "
                "or the model produced invalid JSON."
            )
        return _ParseResult(parsed_output=parsed)


# --- Helpers ----------------------------------------------------------------------


def _build_openai_client(
    *,
    base_url: str,
    api_key: str,
    timeout: float,
    max_retries: int,
) -> openai.OpenAI:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "OpenAIProposerClient requires the [llm] extra: pip install 'orien_import_tool[llm]'"
        ) from exc
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
    )


def _flatten_system(system: Any) -> str:
    """Anthropic accepts a list of ``{type:text, text:..., cache_control:...}``
    blocks; OpenAI accepts a single string. Concatenate them."""
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts: list[str] = []
        for block in system:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return "\n\n".join(parts)
    return str(system)
