# agent5_graph.py — compatibility shim
# Multilingual routing is merged into agent1_graph.py.
# This module re-exports public entry points for backward compatibility.

from agent1_graph import (
    get_language_gap_report,
    run_agent1_for_ticket,
    run_multilingual_agent,
    run_multilingual_batch,
)

__all__ = [
    "get_language_gap_report",
    "run_agent1_for_ticket",
    "run_multilingual_agent",
    "run_multilingual_batch",
]
