"""LLM providers behind one interface (SPEC 2, 4.1 rule 8).

Agents ask for *structured* output only: a Pydantic model. `mock` (the default) returns
deterministic output from a handler registered per task, so the real graphs, checkpointer and
approvals run end to end with no API key. `anthropic` and `openai_compatible` call real models;
the latter works with any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, a gateway), which
is how you keep data in-house.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel

from app.core.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMResult:
    output: BaseModel
    model: str
    input_tokens: int
    output_tokens: int
    ms: int


class LLMProvider(Protocol):
    name: str

    async def structured(
        self, *, task: str, system: str, prompt: str, schema: type[T], context: dict[str, Any]
    ) -> LLMResult: ...


# ---- Mock ----

MockHandler = Callable[[dict[str, Any]], BaseModel]
_MOCK_HANDLERS: dict[str, MockHandler] = {}


def mock_handler(task: str) -> Callable[[MockHandler], MockHandler]:
    """Register the deterministic mock output for an agent task."""

    def register(fn: MockHandler) -> MockHandler:
        _MOCK_HANDLERS[task] = fn
        return fn

    return register


class MockProvider:
    name = "mock"

    async def structured(
        self, *, task: str, system: str, prompt: str, schema: type[T], context: dict[str, Any]
    ) -> LLMResult:
        if task not in _MOCK_HANDLERS:
            raise LookupError(f"No mock handler registered for task {task!r}")
        start = time.perf_counter()
        output = schema.model_validate(_MOCK_HANDLERS[task](context).model_dump())
        return LLMResult(
            output=output,
            model="mock",
            input_tokens=len(prompt) // 4,  # rough, for the trace only
            output_tokens=len(output.model_dump_json()) // 4,
            ms=int((time.perf_counter() - start) * 1000),
        )


# ---- Real models via LangChain ----


class ChatModelProvider:
    def __init__(self, name: str, model: Any, model_name: str) -> None:
        self.name = name
        self._model = model
        self._model_name = model_name

    async def structured(
        self, *, task: str, system: str, prompt: str, schema: type[T], context: dict[str, Any]
    ) -> LLMResult:
        start = time.perf_counter()
        runnable = self._model.with_structured_output(schema, include_raw=True)
        result = cast(
            dict[str, Any], await runnable.ainvoke([("system", system), ("human", prompt)])
        )
        if result.get("parsing_error") or result.get("parsed") is None:
            raise ValueError(f"Model output did not match {schema.__name__}")
        usage = getattr(result.get("raw"), "usage_metadata", None) or {}
        return LLMResult(
            output=result["parsed"],
            model=self._model_name,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            ms=int((time.perf_counter() - start) * 1000),
        )


def build_provider(s: Settings) -> LLMProvider:
    if s.llm_provider == "mock":
        return MockProvider()
    if s.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if not s.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        anthropic = ChatAnthropic(
            model=s.llm_model, api_key=s.anthropic_api_key, temperature=0, max_tokens=4096
        )
        return ChatModelProvider("anthropic", anthropic, s.llm_model)
    from langchain_openai import ChatOpenAI

    if not s.llm_base_url:
        raise ValueError("LLM_PROVIDER=openai_compatible needs LLM_BASE_URL")
    openai = ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.openai_api_key or "not-needed",
        temperature=0,
    )
    return ChatModelProvider("openai_compatible", openai, s.llm_model)


@lru_cache
def get_llm() -> LLMProvider:
    return build_provider(get_settings())
