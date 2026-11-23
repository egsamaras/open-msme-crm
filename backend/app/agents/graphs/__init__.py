"""Importing this package registers every agent graph with the runtime."""

from app.agents.graphs import briefing, cam, demo_followup, ews, kyb

__all__ = ["briefing", "cam", "demo_followup", "ews", "kyb"]
