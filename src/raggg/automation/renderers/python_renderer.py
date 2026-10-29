"""Renderer for the self-contained portable Python controller."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "python"
    / "run_batch.py.tpl"
)


def render_python_controller(_config: Mapping[str, Any]) -> str:
    """Return the portable controller source.

    Runtime values live in ``task_config.json`` so the controller template
    itself stays deterministic and contains no generated path literals.
    """

    return _TEMPLATE.read_text(encoding="utf-8")
