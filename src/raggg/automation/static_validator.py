"""Generation-time validation that never probes target-machine paths."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from raggg.automation.custom_strategy import (
    UnsupportedCustomStrategyError,
    parse_custom_strategy,
)
from raggg.automation.strategy_planner import (
    SweepPlanningError,
    SweepPointLimitError,
    estimate_sweep_point_count,
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    severity: str = "error"


def _issue(code: str, field: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, field=field, message=message)


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _has_illegal_xml_control(value: str) -> bool:
    return any(ord(char) < 32 and char not in "\t\n\r" for char in value)


def _distinct_value_count(variable: Mapping[str, Any]) -> int | None:
    if "values" in variable:
        values = variable.get("values")
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or not values
            or not all(_finite_number(value) for value in values)
        ):
            return None
        return len({float(value) for value in values})

    start = variable.get("start")
    stop = variable.get("stop")
    step = variable.get("step")
    if not all(_finite_number(value) for value in (start, stop, step)):
        return None
    start_number = float(start)
    stop_number = float(stop)
    step_number = float(step)
    if step_number == 0 or (stop_number - start_number) * step_number < 0:
        return None
    span = (stop_number - start_number) / step_number
    return max(0, math.floor(span + 1.0e-10) + 1)


def validate_generation_config(config: Mapping[str, Any]) -> list[ValidationIssue]:
    """Validate local generation semantics without calling ``Path.exists``."""

    issues: list[ValidationIssue] = []

    if config.get("schema_version") != 1:
        issues.append(
            _issue("unsupported_schema", "schema_version", "不支持的配置版本。")
        )

    if not str(config.get("package_dir", "")).strip():
        issues.append(
            _issue("missing_package_dir", "package_dir", "请选择本地压缩包目录。")
        )

    controller = str(config.get("controller", "")).lower()
    if controller not in {"matlab", "python"}:
        issues.append(
            _issue(
                "unsupported_controller",
                "controller",
                "控制器只能选择 MATLAB 或 Python。",
            )
        )

    target = config.get("target", {})
    if not isinstance(target, Mapping):
        target = {}
    waveda_exe = str(target.get("waveda_exe", "")).strip()
    project_file = str(target.get("project_file", "")).strip()
    if not waveda_exe:
        issues.append(
            _issue("missing_waveda_exe", "target.waveda_exe", "请填写 WavEDA.exe。")
        )
    elif not waveda_exe.lower().endswith(".exe"):
        issues.append(
            _issue(
                "invalid_waveda_exe",
                "target.waveda_exe",
                "WavEDA 程序路径必须指向 .exe 文件。",
            )
        )
    if not project_file:
        issues.append(
            _issue("missing_project_file", "target.project_file", "请填写 .tsp 工程。")
        )
    elif not project_file.lower().endswith(".tsp"):
        issues.append(
            _issue(
                "invalid_project_file",
                "target.project_file",
                "工程路径必须指向 .tsp 文件。",
            )
        )

    for field, value in (
        ("target.waveda_exe", waveda_exe),
        ("target.project_file", project_file),
    ):
        if _has_illegal_xml_control(value):
            issues.append(
                _issue("illegal_xml_character", field, "路径含有 XML 不允许的控制字符。")
            )

    sweep = config.get("sweep", {})
    if not isinstance(sweep, Mapping):
        sweep = {}
    strategy = str(sweep.get("strategy", "")).lower()
    if strategy not in {
        "range",
        "explicit_values",
        "single_param",
        "dual_param",
        "custom",
        "builtin_sweep",
    }:
        issues.append(
            _issue("unsupported_strategy", "sweep.strategy", "不支持该扫描策略。")
        )

    if strategy == "builtin_sweep":
        issues.append(
            _issue(
                "builtin_sweep_unavailable",
                "sweep.strategy",
                "Built-in WavEDA sweep requires a verified project template.",
            )
        )

    custom_strategy = None
    if strategy == "custom":
        custom_description = str(sweep.get("custom_description", "")).strip()
        if not custom_description:
            issues.append(
                _issue(
                    "custom_description_required",
                    "sweep.custom_description",
                    "自定义策略描述不能为空。",
                )
            )
        else:
            try:
                custom_strategy = parse_custom_strategy(custom_description)
            except UnsupportedCustomStrategyError as exc:
                issues.append(
                    _issue(
                        "unsupported_custom_strategy",
                        "sweep.custom_description",
                        str(exc),
                    )
                )

    variables = sweep.get("variables", [])
    if not isinstance(variables, Sequence) or isinstance(variables, (str, bytes)):
        variables = []
    if len(variables) > 2:
        issues.append(
            _issue(
                "unsupported_variable_count",
                "sweep.variables",
                "Only one or two sweep variables are supported.",
            )
        )
    if strategy == "single_param" and len(variables) != 1:
        issues.append(
            _issue(
                "single_param_count",
                "sweep.variables",
                "single_param requires exactly one variable.",
            )
        )
    if strategy == "dual_param" and len(variables) != 2:
        issues.append(
            _issue(
                "dual_param_count",
                "sweep.variables",
                "dual_param requires exactly two variables.",
            )
        )
    if not variables:
        issues.append(
            _issue("missing_variables", "sweep.variables", "至少需要一个扫描变量。")
        )

    seen_names: set[str] = set()
    for index, variable in enumerate(variables):
        field = f"sweep.variables[{index}]"
        if not isinstance(variable, Mapping):
            issues.append(_issue("invalid_variable", field, "扫描变量格式无效。"))
            continue
        variable_keys = set(variable)
        if strategy == "range" and variable_keys != {
            "name",
            "start",
            "stop",
            "step",
        }:
            issues.append(
                _issue(
                    "range_variable_shape",
                    field,
                    "range 策略的变量只能包含 name、start、stop 和 step。",
                )
            )
        elif strategy == "explicit_values" and variable_keys != {
            "name",
            "values",
        }:
            issues.append(
                _issue(
                    "explicit_values_variable_shape",
                    field,
                    "explicit_values 策略的变量只能包含 name 和 values。",
                )
            )
        elif strategy in {"single_param", "dual_param", "custom"}:
            valid_alias_shape = variable_keys in (
                {"name", "values"},
                {"name", "start", "stop", "step"},
            )
            if not valid_alias_shape:
                issues.append(
                    _issue(
                        "invalid_variable_shape",
                        field,
                        "Use explicit values or a start/stop/step range.",
                    )
                )
        name = str(variable.get("name", "")).strip()
        if not name:
            issues.append(_issue("missing_variable_name", f"{field}.name", "变量名不能为空。"))
        else:
            normalized_name = name.casefold()
            if normalized_name in seen_names:
                issues.append(
                    _issue("duplicate_variable", f"{field}.name", "扫描变量名不能重复。")
                )
            seen_names.add(normalized_name)
            if _has_illegal_xml_control(name):
                issues.append(
                    _issue(
                        "illegal_xml_character",
                        f"{field}.name",
                        "变量名含有 XML 不允许的控制字符。",
                    )
                )

        if "values" in variable:
            values = variable.get("values")
            if (
                not isinstance(values, Sequence)
                or isinstance(values, (str, bytes))
                or not values
            ):
                issues.append(
                    _issue("missing_values", f"{field}.values", "显式扫描值不能为空。")
                )
            elif not all(_finite_number(value) for value in values):
                issues.append(
                    _issue("invalid_value", f"{field}.values", "扫描值必须是有限数值。")
                )
        else:
            for key in ("start", "stop", "step"):
                if not _finite_number(variable.get(key)):
                    issues.append(
                        _issue(
                            "invalid_range_value",
                            f"{field}.{key}",
                            "范围起点、终点和步长必须是有限数值。",
                        )
                    )
            step = variable.get("step")
            start = variable.get("start")
            stop = variable.get("stop")
            if _finite_number(step) and float(step) == 0:
                issues.append(_issue("zero_step", f"{field}.step", "扫描步长不能为 0。"))
            elif all(_finite_number(value) for value in (start, stop, step)):
                if (float(stop) - float(start)) * float(step) < 0:
                    issues.append(
                        _issue(
                            "wrong_step_direction",
                            f"{field}.step",
                            "扫描步长方向与起止范围不一致。",
                        )
                    )

    try:
        estimate_sweep_point_count(config)
    except SweepPointLimitError as exc:
        issues.append(
            _issue(
                "too_many_sweep_points",
                "sweep.variables",
                str(exc),
            )
        )
    except SweepPlanningError:
        pass

    if custom_strategy is not None and custom_strategy.is_adaptive:
        distinct_combination_count = 1
        counts_are_valid = True
        for variable in variables:
            if not isinstance(variable, Mapping):
                counts_are_valid = False
                break
            value_count = _distinct_value_count(variable)
            if value_count is None:
                counts_are_valid = False
                break
            distinct_combination_count *= value_count
        if counts_are_valid and distinct_combination_count < 2:
            issues.append(
                _issue(
                    "adaptive_requires_multiple_points",
                    "sweep.variables",
                    "粗扫阶段至少 2 个不同参数组合才能执行自适应细扫。",
                )
            )

    results = config.get("results", [])
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        results = []
    if not results:
        issues.append(_issue("missing_results", "results", "至少需要一个导出结果。"))
    for index, result in enumerate(results):
        field = f"results[{index}]"
        if not isinstance(result, Mapping):
            issues.append(_issue("invalid_result", field, "结果配置格式无效。"))
            continue
        name = str(result.get("name", "")).strip()
        if not name:
            issues.append(_issue("missing_result_name", f"{field}.name", "结果节点名不能为空。"))
        elif _has_illegal_xml_control(name):
            issues.append(
                _issue(
                    "illegal_xml_character",
                    f"{field}.name",
                    "结果名含有 XML 不允许的控制字符。",
                )
            )
        if str(result.get("type", "")).lower() not in {"port", "obv"}:
            issues.append(
                _issue(
                    "unsupported_result_type",
                    f"{field}.type",
                    "结果类型只能是 port 或 obv。",
                )
            )
        traces = result.get("traces")
        if (
            not isinstance(traces, list)
            or not traces
            or any(
                not isinstance(trace, str) or not trace.strip()
                for trace in traces
            )
        ):
            issues.append(
                _issue(
                    "invalid_result_traces",
                    f"{field}.traces",
                    "结果曲线必须是至少包含一个非空名称的字符串列表。",
                )
            )

    if custom_strategy is not None and custom_strategy.is_adaptive:
        port_results = [
            result
            for result in results
            if isinstance(result, Mapping)
            and str(result.get("type", "")).lower() == "port"
            and isinstance(result.get("traces"), Sequence)
            and not isinstance(result.get("traces"), (str, bytes))
            and result.get("traces")
        ]
        if not port_results:
            issues.append(
                _issue(
                    "adaptive_requires_port",
                    "results",
                    "粗扫再细扫需要至少一个带曲线的 Port 结果。",
                )
            )

    frequency = config.get("frequency", {})
    if not isinstance(frequency, Mapping):
        frequency = {}
    if not _finite_number(frequency.get("target")):
        issues.append(
            _issue("invalid_target_frequency", "frequency.target", "目标频率必须是有限数值。")
        )
    if str(frequency.get("unit", "")).lower() not in {
        "hz",
        "khz",
        "mhz",
        "ghz",
    }:
        issues.append(
            _issue("invalid_frequency_unit", "frequency.unit", "不支持该频率单位。")
        )

    if (
        "data_frequency_unit" in config
        and str(config.get("data_frequency_unit", "")).lower()
        not in {"hz", "khz", "mhz", "ghz"}
    ):
        issues.append(
            _issue(
                "invalid_data_frequency_unit",
                "data_frequency_unit",
                "Data frequency unit must be Hz, kHz, MHz, or GHz.",
            )
        )

    runtime = config.get("runtime", {})
    if not isinstance(runtime, Mapping):
        runtime = {}
    timeout = runtime.get("timeout_seconds")
    if not _finite_number(timeout) or float(timeout) <= 0:
        issues.append(
            _issue("invalid_timeout", "runtime.timeout_seconds", "超时时间必须大于 0。")
        )
    attempts = runtime.get("max_attempts")
    if (
        not _finite_number(attempts)
        or float(attempts) < 1
        or not float(attempts).is_integer()
    ):
        issues.append(
            _issue(
                "invalid_max_attempts",
                "runtime.max_attempts",
                "最大尝试次数必须是大于等于 1 的整数。",
            )
        )
    if type(runtime.get("force_remesh")) is not bool:
        issues.append(
            _issue(
                "invalid_force_remesh",
                "runtime.force_remesh",
                "force_remesh 必须是布尔值。",
            )
        )
    if type(runtime.get("resume")) is not bool:
        issues.append(
            _issue(
                "invalid_resume",
                "runtime.resume",
                "resume 必须是布尔值。",
            )
        )

    return issues
