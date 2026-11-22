from typing import Any


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    """Alembic filter: only manage the public schema.

    LangGraph's checkpointer owns the `langgraph` schema (SPEC 3). Without this filter,
    autogenerate would propose dropping the checkpoint tables.
    """
    if type_ == "schema":
        return name in (None, "public")
    return True
