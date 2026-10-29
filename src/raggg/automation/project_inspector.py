"""Read-only inspection of WavEDA script XML."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VariableDefinition:
    name: str
    value: str
    is_expression: bool


@dataclass(frozen=True, slots=True)
class ResultDefinition:
    name: str
    result_type: str
    file: str


@dataclass(frozen=True, slots=True)
class ProjectInspection:
    project_file: str | None
    variables: tuple[VariableDefinition, ...]
    results: tuple[ResultDefinition, ...]


def _is_expression(value: str) -> bool:
    try:
        return not math.isfinite(float(value))
    except ValueError:
        return True


def inspect_script_xml(xml_text: str) -> ProjectInspection:
    """Discover project, variable, and result commands without modifying XML."""

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"XML 解析失败: {exc}") from exc

    project_file: str | None = None
    variables: list[VariableDefinition] = []
    results: list[ResultDefinition] = []

    for command in root.iter("command"):
        command_type = command.get("cmdType", "").lower()
        object_type = command.get("obj1", "").lower()
        if command_type == "load" and object_type == "project":
            if project_file is None:
                project_file = command.get("file", "")
        elif command_type == "modify" and object_type in {"var", "variable"}:
            value = command.get("value", "")
            variables.append(
                VariableDefinition(
                    name=command.get("name", ""),
                    value=value,
                    is_expression=_is_expression(value),
                )
            )
        elif command_type == "export" and object_type == "result":
            result_type = command.get("obj2", "").lower()
            if result_type == "observer":
                result_type = "obv"
            results.append(
                ResultDefinition(
                    name=command.get("name", ""),
                    result_type=result_type,
                    file=command.get("file", ""),
                )
            )

    return ProjectInspection(
        project_file=project_file,
        variables=tuple(variables),
        results=tuple(results),
    )
