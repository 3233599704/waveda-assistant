"""Normalized configuration for portable WavEDA script packages."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = 1


def _number_or_original(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _normalize_variables(sweep_vars: Any) -> list[dict[str, Any]]:
    if sweep_vars is None:
        return []

    if isinstance(sweep_vars, Mapping):
        items = sweep_vars.items()
    elif isinstance(sweep_vars, Sequence) and not isinstance(
        sweep_vars, (str, bytes)
    ):
        items = (
            (item.get("name", ""), item)
            for item in sweep_vars
            if isinstance(item, Mapping)
        )
    else:
        return []

    variables: list[dict[str, Any]] = []
    for raw_name, raw_spec in items:
        variable: dict[str, Any] = {"name": str(raw_name).strip()}
        if isinstance(raw_spec, Mapping):
            for key in ("start", "stop", "step"):
                if key in raw_spec:
                    variable[key] = _number_or_original(raw_spec[key])
            if "values" in raw_spec:
                values = raw_spec["values"]
                if isinstance(values, Sequence) and not isinstance(
                    values, (str, bytes)
                ):
                    variable["values"] = [
                        _number_or_original(value) for value in values
                    ]
                else:
                    variable["values"] = values
        elif isinstance(raw_spec, Sequence) and not isinstance(
            raw_spec, (str, bytes)
        ):
            variable["values"] = [
                _number_or_original(value) for value in raw_spec
            ]
        else:
            variable["values"] = raw_spec
        variables.append(variable)
    return variables


def _normalize_results(results: Any) -> list[dict[str, Any]]:
    if results is None:
        results = [
            {"name": "Port_S_data_1", "type": "port", "traces": ["S11 dB"]}
        ]
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        return []

    normalized: list[dict[str, Any]] = []
    for raw_result in results:
        if not isinstance(raw_result, Mapping):
            continue
        result_type = str(raw_result.get("type", "port")).strip().lower()
        if result_type == "observer":
            result_type = "obv"
        traces = raw_result.get("traces", [])
        if isinstance(traces, Sequence) and not isinstance(traces, (str, bytes)):
            normalized_traces = [
                trace.strip() if isinstance(trace, str) else trace
                for trace in traces
            ]
        else:
            normalized_traces = traces
        normalized.append(
            {
                "name": str(raw_result.get("name", "")).strip(),
                "type": result_type,
                "traces": normalized_traces,
            }
        )
    return normalized


def build_task_config(
    *,
    package_dir: str,
    waveda_exe: str,
    project_file: str,
    controller: str = "matlab",
    sweep_vars: Any = None,
    strategy: str = "explicit_values",
    results: Any = None,
    custom_description: str = "",
    target_freq: float = 2.45,
    frequency_unit: str = "GHz",
    data_frequency_unit: str | None = None,
    timeout_seconds: int = 1800,
    max_attempts: int = 3,
    force_remesh: bool = True,
    resume: bool = True,
) -> dict[str, Any]:
    """Build a serializable task configuration without probing target paths."""

    config = {
        "schema_version": SCHEMA_VERSION,
        "package_dir": str(package_dir).strip(),
        "controller": str(controller).strip().lower(),
        "target": {
            "waveda_exe": str(waveda_exe).strip(),
            "project_file": str(project_file).strip(),
        },
        "sweep": {
            "strategy": str(strategy).strip().lower(),
            "variables": _normalize_variables(sweep_vars),
            "custom_description": str(custom_description).strip(),
        },
        "results": _normalize_results(results),
        "frequency": {
            "target": _number_or_original(target_freq),
            "unit": str(frequency_unit).strip(),
        },
        "runtime": {
            "timeout_seconds": _number_or_original(timeout_seconds),
            "max_attempts": _number_or_original(max_attempts),
            "force_remesh": force_remesh,
            "resume": resume,
        },
    }
    if data_frequency_unit is not None:
        config["data_frequency_unit"] = str(data_frequency_unit).strip()
    return config


def task_signature_payload(config: Mapping[str, Any]) -> str:
    """Return canonical JSON for target-relevant task configuration."""
    payload = copy.deepcopy(dict(config))
    payload.pop("package_dir", None)
    payload.pop("task_signature", None)
    payload.pop("task_signature_payload", None)
    payload.pop("_resolved_data_frequency_unit", None)
    payload.pop("data_frequency_unit_resolved", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def task_signature(config: Mapping[str, Any]) -> str:
    """Return a stable signature for target-relevant task configuration."""

    canonical = task_signature_payload(config)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
