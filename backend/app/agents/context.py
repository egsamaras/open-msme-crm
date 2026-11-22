"""Per-run context and tracing.

The runner sets an `AgentContext` in a context variable around each graph execution, so nodes can
reach the run's ids, the LLM and the tracer without putting them in graph state (state is
checkpointed and must stay plain JSON).
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.agents.llm import LLMProvider, T
from app.models.base import utcnow
from app.services.audit import canonical_json


class CitationError(ValueError):
    """An LLM output cited a record the agent never gave it (SPEC 4.1, rule 4)."""


def _jsonable(value: Any) -> Any:
    import json

    return json.loads(canonical_json(value))


@dataclass
class Tracer:
    events: list[dict[str, Any]] = field(default_factory=list)

    def add(self, event: str, **data: Any) -> None:
        self.events.append({"type": event, "at": utcnow().isoformat(), **_jsonable(data)})

    def drain(self) -> list[dict[str, Any]]:
        out, self.events = self.events, []
        return out


@dataclass
class AgentContext:
    run_id: uuid.UUID
    thread_id: str
    agent_name: str
    user_id: uuid.UUID | None
    llm: LLMProvider
    tracer: Tracer
    started_at: datetime = field(default_factory=utcnow)

    def tool(self, name: str, inputs: dict[str, Any], output: Any) -> None:
        """Record a deterministic tool call (data fetch, calculation) in the trace."""
        self.tracer.add("tool", name=name, input=inputs, output=output)

    async def generate(
        self,
        *,
        task: str,
        system: str,
        prompt: str,
        schema: type[T],
        context: dict[str, Any],
        allowed_sources: set[uuid.UUID],
    ) -> T:
        """Structured LLM call with citation checking. Never use the LLM for arithmetic."""
        result = await self.llm.structured(
            task=task, system=system, prompt=prompt, schema=schema, context=context
        )
        output: BaseModel = result.output
        cited = {uuid.UUID(str(i)) for i in getattr(output, "source_record_ids", [])}
        unknown = cited - allowed_sources
        self.tracer.add(
            "llm",
            task=task,
            provider=self.llm.name,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            ms=result.ms,
            cited=sorted(str(c) for c in cited),
            rejected_citations=sorted(str(u) for u in unknown),
        )
        if unknown:
            raise CitationError(f"Output cited {len(unknown)} record(s) it was not given")
        return output  # type: ignore[return-value]


_CTX: ContextVar[AgentContext] = ContextVar("agent_context")


def current() -> AgentContext:
    try:
        return _CTX.get()
    except LookupError as e:
        raise RuntimeError("Agent nodes must run inside app.agents.runtime") from e


def set_context(ctx: AgentContext) -> object:
    return _CTX.set(ctx)


def reset_context(token: object) -> None:
    _CTX.reset(token)  # type: ignore[arg-type]
