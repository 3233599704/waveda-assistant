"""Deterministic sweep-point planning shared by both controller languages."""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from raggg.automation.custom_strategy import (
    UnsupportedCustomStrategyError,
    parse_custom_strategy,
)

MAX_SWEEP_POINTS = 10_000


class SweepPlanningError(ValueError):
    """Raised when a sweep strategy cannot produce a safe deterministic plan."""


class SweepPointLimitError(SweepPlanningError):
    """Raised before expansion when a sweep exceeds the hard point limit."""


@dataclass(frozen=True, slots=True)
class SweepAssignment:
    name: str
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class SweepPoint:
    id: str
    assignments: tuple[SweepAssignment, ...]

    @property
    def values(self) -> Mapping[str, float]:
        return MappingProxyType(
            {assignment.name: assignment.value for assignment in self.assignments}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "assignments": [
                assignment.to_dict() for assignment in self.assignments
            ],
        }


@dataclass(frozen=True, slots=True)
class SweepPlan:
    points: tuple[SweepPoint, ...]
    custom_description: str = ""
    adaptive_parameters: dict[str, Any] | None = None

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def estimated_point_count(self) -> int:
        return len(self.points)

    @property
    def endpoints(self) -> tuple[SweepPoint, ...]:
        if not self.points:
            return ()
        if len(self.points) == 1:
            return (self.points[0],)
        return (self.points[0], self.points[-1])

    @property
    def smoke_point(self) -> SweepPoint | None:
        if len(self.points) < 2:
            return None
        baseline = self.points[0].assignments
        return next(
            (
                point
                for point in self.points[1:]
                if point.assignments != baseline
            ),
            None,
        )


def _explicit_values(variable: Mapping[str, Any]) -> tuple[float, ...]:
    values = variable.get("values")
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or not values
    ):
        raise SweepPlanningError(
            f"Variable {variable.get('name', '')!r} has no explicit values."
        )
    return tuple(float(value) for value in values)


def _range_values(variable: Mapping[str, Any]) -> tuple[float, ...]:
    try:
        start = Decimal(str(variable["start"]))
        stop = Decimal(str(variable["stop"]))
        step = Decimal(str(variable["step"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SweepPlanningError(
            f"Variable {variable.get('name', '')!r} has an invalid range."
        ) from exc
    if step == 0:
        raise SweepPlanningError("Sweep step cannot be zero.")
    if (stop - start) * step < 0:
        raise SweepPlanningError("Sweep step direction does not reach the stop.")
    compare = (
        (lambda value: value <= stop)
        if step > 0
        else (lambda value: value >= stop)
    )
    values: list[float] = []
    current = start
    while compare(current):
        values.append(float(current))
        current = start + step * len(values)
    if not values:
        raise SweepPlanningError("Sweep range produced no points.")
    return tuple(values)


def _values_for(variable: Mapping[str, Any], strategy: str) -> tuple[float, ...]:
    if strategy == "range":
        return _range_values(variable)
    if strategy == "explicit_values":
        return _explicit_values(variable)
    if "values" in variable:
        return _explicit_values(variable)
    return _range_values(variable)


def _range_value_count(variable: Mapping[str, Any]) -> int:
    try:
        start = Decimal(str(variable["start"]))
        stop = Decimal(str(variable["stop"]))
        step = Decimal(str(variable["step"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise SweepPlanningError(
            f"Variable {variable.get('name', '')!r} has an invalid range."
        ) from exc
    if step == 0:
        raise SweepPlanningError("Sweep step cannot be zero.")
    distance = stop - start
    if distance * step < 0:
        raise SweepPlanningError("Sweep step direction does not reach the stop.")
    return int(distance // step) + 1


def _value_count_for(variable: Mapping[str, Any], strategy: str) -> int:
    if strategy == "range":
        return _range_value_count(variable)
    if strategy == "explicit_values":
        values = variable.get("values")
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or not values
        ):
            raise SweepPlanningError(
                f"Variable {variable.get('name', '')!r} has no explicit values."
            )
        return len(values)
    if "values" in variable:
        return _value_count_for(variable, "explicit_values")
    return _range_value_count(variable)


def estimate_sweep_point_count(config: Mapping[str, Any]) -> int:
    """Return point count and fail before materializing an oversized sweep."""

    sweep = config.get("sweep", {})
    if not isinstance(sweep, Mapping):
        raise SweepPlanningError("Sweep configuration is missing.")
    variables = sweep.get("variables", [])
    if (
        not isinstance(variables, Sequence)
        or isinstance(variables, (str, bytes))
        or len(variables) not in (1, 2)
    ):
        raise SweepPlanningError("Only one or two sweep variables are supported.")
    strategy = str(sweep.get("strategy", "")).lower()
    total = 1
    for variable in variables:
        if not isinstance(variable, Mapping):
            raise SweepPlanningError("Each sweep variable must be an object.")
        total *= _value_count_for(variable, strategy)
        if total > MAX_SWEEP_POINTS:
            raise SweepPointLimitError(
                f"Sweep would create {total:,} points; "
                f"the hard limit is {MAX_SWEEP_POINTS:,}."
            )
    return total


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    return cleaned or "var"


def _filename_token(value: float) -> str:
    decimal = Decimal(str(value))
    if decimal == 0:
        decimal = Decimal(0)
    text = format(decimal, "f").rstrip("0").rstrip(".")
    if not text or text == "-0":
        text = "0"
    if text.startswith("-"):
        text = f"m{text[1:]}"
    return text.replace(".", "p").replace("+", "")


def plan_sweep(config: Mapping[str, Any]) -> SweepPlan:
    """Create a stable serial sweep plan for one or two variables."""

    sweep = config.get("sweep", {})
    if not isinstance(sweep, Mapping):
        raise SweepPlanningError("Sweep configuration is missing.")
    strategy = str(sweep.get("strategy", "")).lower()
    if strategy == "builtin_sweep":
        raise SweepPlanningError(
            "Built-in WavEDA sweep requires a verified project template "
            "and is currently unavailable."
        )
    if strategy not in {
        "range",
        "explicit_values",
        "single_param",
        "dual_param",
        "custom",
    }:
        raise SweepPlanningError(f"Unsupported sweep strategy: {strategy}")

    custom_strategy = None
    if strategy == "custom":
        try:
            custom_strategy = parse_custom_strategy(
                str(sweep.get("custom_description", ""))
            )
        except UnsupportedCustomStrategyError as exc:
            raise SweepPlanningError(str(exc)) from exc

    variables = sweep.get("variables", [])
    if (
        not isinstance(variables, Sequence)
        or isinstance(variables, (str, bytes))
    ):
        raise SweepPlanningError("Sweep variables must be a list.")
    if len(variables) not in (1, 2):
        raise SweepPlanningError("Only one or two sweep variables are supported.")
    if strategy == "single_param" and len(variables) != 1:
        raise SweepPlanningError("single_param requires exactly one variable.")
    if strategy == "dual_param" and len(variables) != 2:
        raise SweepPlanningError("dual_param requires exactly two variables.")

    normalized_variables: list[Mapping[str, Any]] = []
    for variable in variables:
        if not isinstance(variable, Mapping):
            raise SweepPlanningError("Each sweep variable must be an object.")
        name = str(variable.get("name", "")).strip()
        if not name:
            raise SweepPlanningError("Sweep variable name cannot be empty.")
        normalized_variables.append(variable)

    estimate_sweep_point_count(config)
    value_sets = [
        _values_for(variable, strategy)
        for variable in normalized_variables
    ]

    points: list[SweepPoint] = []
    for index, combination in enumerate(
        itertools.product(*value_sets), start=1
    ):
        assignments = tuple(
            SweepAssignment(str(variable["name"]), float(value))
            for variable, value in zip(normalized_variables, combination)
        )
        suffix = "_".join(
            f"{_safe_name(assignment.name)}_"
            f"{_filename_token(assignment.value)}"
            for assignment in assignments
        )
        points.append(SweepPoint(f"p{index:04d}_{suffix}", assignments))
    adaptive_parameters = None
    if custom_strategy is not None and custom_strategy.is_adaptive:
        distinct_combinations = {
            tuple(
                (assignment.name, assignment.value)
                for assignment in point.assignments
            )
            for point in points
        }
        if len(distinct_combinations) < 2:
            raise SweepPlanningError(
                "粗扫阶段至少 2 个不同参数组合才能执行自适应细扫。"
            )
        port_result = next(
            (
                result
                for result in config.get("results", [])
                if isinstance(result, Mapping)
                and str(result.get("type", "")).lower() == "port"
                and isinstance(result.get("traces"), Sequence)
                and not isinstance(result.get("traces"), (str, bytes))
                and result.get("traces")
            ),
            None,
        )
        if port_result is None:
            raise SweepPlanningError(
                "粗扫再细扫需要至少一个带曲线的 Port 结果。"
            )
        adaptive_parameters = {
            "mode": "adaptive_coarse_to_fine",
            "refinement_factor": 5,
            "neighborhood": "adjacent_coarse_interval",
            "exclude_stage1_points": True,
            "selection_metric": {
                "result_type": "port",
                "result_name": str(port_result.get("name", "")),
                "trace": str(port_result["traces"][0]),
                "metric": "target_frequency_value",
                "goal": "minimize",
            },
        }

    return SweepPlan(
        points=tuple(points),
        custom_description=str(sweep.get("custom_description", "")),
        adaptive_parameters=adaptive_parameters,
    )
