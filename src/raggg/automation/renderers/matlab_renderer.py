"""Renderer for the self-contained portable MATLAB controller."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "matlab"
    / "run_batch.m.tpl"
)


def render_matlab_controller(_config: Mapping[str, Any]) -> str:
    """Return deterministic MATLAB controller source."""

    return _TEMPLATE.read_text(encoding="utf-8")
