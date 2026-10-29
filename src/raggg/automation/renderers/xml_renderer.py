"""Deterministic WavEDA XML template rendering and validation."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from typing import Any

from raggg.automation.static_validator import ValidationIssue
from raggg.automation.template_sentinels import find_template_sentinel

_CANONICAL_ATTRIBUTES = {
    "cmdtype": "cmdType",
    "obj1": "obj1",
    "obj2": "obj2",
    "name": "name",
    "value": "value",
    "file": "file",
    "solver": "solver",
}


def _initial_value(variable: Mapping[str, Any]) -> Any:
    values = variable.get("values")
    if (
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes))
        and values
    ):
        return values[0]
    return variable.get("start", 0)


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isfinite(number) and number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _result_file(index: int, result_type: str) -> str:
    return f"output/raw/result_{index:02d}_{result_type}.txt"


def render_template_xml(config: Mapping[str, Any]) -> str:
    """Render one deterministic base XML script from normalized config."""

    root = ET.Element("script", {"version": "1.0"})
    target = config.get("target", {})
    ET.SubElement(
        root,
        "command",
        {
            "cmdType": "load",
            "obj1": "project",
            "file": str(target.get("project_file", "")),
        },
    )

    sweep = config.get("sweep", {})
    variables = sweep.get("variables", [])
    for variable in variables:
        ET.SubElement(
            root,
            "command",
            {
                "cmdType": "modify",
                "obj1": "var",
                "name": str(variable.get("name", "")),
                "value": _format_number(_initial_value(variable)),
            },
        )

    runtime = config.get("runtime", {})
    if bool(runtime.get("force_remesh", True)):
        ET.SubElement(
            root,
            "command",
            {"cmdType": "delete", "obj1": "mesh"},
        )

    ET.SubElement(root, "command", {"cmdType": "sim", "solver": "auto"})

    for index, result in enumerate(config.get("results", []), start=1):
        result_type = str(result.get("type", "")).lower()
        if result_type == "observer":
            result_type = "obv"
        ET.SubElement(
            root,
            "command",
            {
                "cmdType": "export",
                "obj1": "result",
                "obj2": result_type,
                "name": str(result.get("name", "")),
                "file": _result_file(index, result_type),
            },
        )

    ET.SubElement(root, "command", {"cmdType": "close", "obj1": "project"})
    ET.SubElement(root, "command", {"cmdType": "close", "obj1": "gui"})
    ET.indent(root, space="    ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def _issue(code: str, field: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, field=field, message=message)


def _commands(
    root: ET.Element,
    *,
    cmd_type: str,
    obj1: str | None = None,
) -> list[ET.Element]:
    matches = []
    for command in root.iter("command"):
        if command.get("cmdType", "").lower() != cmd_type:
            continue
        if obj1 is not None and command.get("obj1", "").lower() != obj1:
            continue
        matches.append(command)
    return matches


def validate_template_xml(
    xml_text: str, config: Mapping[str, Any]
) -> list[ValidationIssue]:
    """Validate that a script template matches its normalized configuration."""

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return [_issue("malformed_xml", "template.xml", f"XML 解析失败: {exc}")]

    issues: list[ValidationIssue] = []
    if root.tag != "script":
        issues.append(_issue("invalid_root", "template.xml", "XML 根节点必须是 script。"))

    for element_index, element in enumerate(root.iter()):
        for node_kind in ("text", "tail"):
            sentinel = find_template_sentinel(getattr(element, node_kind))
            if sentinel is not None:
                issues.append(
                    _issue(
                        "unresolved_template_sentinel",
                        f"element[{element_index}].{node_kind}",
                        f"XML {node_kind} 节点含有未解析模板标记 {sentinel}。",
                    )
                )

    for command_index, command in enumerate(root.iter("command")):
        for attribute in command.attrib:
            expected = _CANONICAL_ATTRIBUTES.get(attribute.lower())
            if expected is not None and attribute != expected:
                issues.append(
                    _issue(
                        "invalid_attribute_casing",
                        f"command[{command_index}].{attribute}",
                        f"命令属性应写为 {expected}。",
                    )
                )

    loads = _commands(root, cmd_type="load", obj1="project")
    if len(loads) != 1:
        issues.append(
            _issue("project_load_count", "template.xml", "必须且只能有一条工程加载命令。")
        )
    elif loads[0].get("file") != config.get("target", {}).get("project_file"):
        issues.append(
            _issue("project_path_mismatch", "target.project_file", "工程路径与配置不一致。")
        )

    modifications = _commands(root, cmd_type="modify", obj1="var")
    variables = config.get("sweep", {}).get("variables", [])
    for index, variable in enumerate(variables):
        name = str(variable.get("name", ""))
        matching_modifications = [
            command
            for command in modifications
            if command.get("name", "").casefold() == name.casefold()
        ]
        if len(matching_modifications) != 1:
            issues.append(
                _issue(
                    "variable_command_count",
                    f"sweep.variables[{index}]",
                    f"变量 {name} 必须且只能对应一条 modify 命令。",
                )
            )
        else:
            expected_value = _format_number(_initial_value(variable))
            if matching_modifications[0].get("value") != expected_value:
                issues.append(
                    _issue(
                        "variable_value_mismatch",
                        f"sweep.variables[{index}].value",
                        f"变量 {name} 的 XML 初值必须等于配置首值 {expected_value}。",
                    )
                )
    if len(modifications) != len(variables):
        issues.append(
            _issue(
                "modification_count",
                "template.xml",
                "modify 命令总数必须与配置变量数一致。",
            )
        )

    deletes = _commands(root, cmd_type="delete", obj1="mesh")
    expected_delete_count = (
        1 if config.get("runtime", {}).get("force_remesh", True) else 0
    )
    if len(deletes) != expected_delete_count:
        issues.append(
            _issue(
                "mesh_delete_count",
                "runtime.force_remesh",
                "删除网格命令与 force_remesh 配置不一致。",
            )
        )

    simulations = _commands(root, cmd_type="sim")
    if len(simulations) != 1:
        issues.append(
            _issue("simulation_count", "template.xml", "必须且只能有一条 sim 命令。")
        )

    exports = _commands(root, cmd_type="export", obj1="result")
    results = config.get("results", [])
    for index, result in enumerate(results):
        result_type = str(result.get("type", "")).lower().replace(
            "observer", "obv"
        )
        key = (str(result.get("name", "")).casefold(), result_type)
        matching_exports = [
            command
            for command in exports
            if (
                command.get("name", "").casefold(),
                command.get("obj2", "").lower().replace("observer", "obv"),
            )
            == key
        ]
        if len(matching_exports) != 1:
            issues.append(
                _issue(
                    "result_command_count",
                    f"results[{index}]",
                    f"结果 {result.get('name', '')} 必须且只能对应一条 export 命令。",
                )
            )
        else:
            expected_file = _result_file(index + 1, result_type)
            if matching_exports[0].get("file") != expected_file:
                issues.append(
                    _issue(
                        "result_file_mismatch",
                        f"results[{index}].file",
                        f"结果 {result.get('name', '')} 必须导出到 {expected_file}。",
                    )
                )
    if len(exports) != len(results):
        issues.append(
            _issue(
                "export_count",
                "template.xml",
                "export 命令总数必须与配置结果数一致。",
            )
        )

    return issues
