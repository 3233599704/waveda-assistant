from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.automation.project_inspector import inspect_script_xml
from raggg.automation.renderers.xml_renderer import (
    render_template_xml,
    validate_template_xml,
)
from raggg.automation.task_config import build_task_config


def make_config(*, force_remesh=True):
    return build_task_config(
        package_dir=r"C:\local packages\sweep",
        waveda_exe=r"D:\Program Files\WavEDA\WavEDA.exe",
        project_file=r"E:\remote projects\filter & antenna <v2>.tsp",
        controller="python",
        sweep_vars={
            "Length & Width": [9.0, 9.5, 10.0, 10.5, 11.0],
            "Gap": [0.2, 0.3],
        },
        strategy="explicit_values",
        results=[
            {"name": "Port & S<1>", "type": "port", "traces": ["S11 dB"]},
            {"name": "E field <peak>", "type": "observer", "traces": ["E"]},
        ],
        force_remesh=force_remesh,
    )


def issue_codes(xml_text, config):
    return {issue.code for issue in validate_template_xml(xml_text, config)}


def test_inspection_discovers_variables_results_and_expression_variables():
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<script version="1.0">
  <command cmdType="load" obj1="project" file="E:\\model.tsp" />
  <command cmdType="modify" obj1="var" name="width" value="1.5" />
  <command cmdType="modify" obj1="var" name="derived" value="2*width" />
  <command cmdType="export" obj1="result" obj2="port"
           name="Port_S_data_1" file="./port.txt" />
  <command cmdType="export" obj1="result" obj2="obv"
           name="Observer_1" file="./observer.txt" />
</script>"""

    inspection = inspect_script_xml(xml_text)

    assert [(item.name, item.value, item.is_expression) for item in inspection.variables] == [
        ("width", "1.5", False),
        ("derived", "2*width", True),
    ]
    assert [(item.name, item.result_type) for item in inspection.results] == [
        ("Port_S_data_1", "port"),
        ("Observer_1", "obv"),
    ]
    assert inspection.project_file == r"E:\model.tsp"


def test_rendering_is_deterministic_and_escapes_xml_sensitive_values():
    config = make_config()

    first = render_template_xml(config)
    second = render_template_xml(config)
    root = ET.fromstring(first)

    assert first == second
    assert "&amp;" in first
    assert "&lt;" in first
    load = root.find("./command[@cmdType='load']")
    assert load is not None
    assert load.get("file") == config["target"]["project_file"]
    assert validate_template_xml(first, config) == []


@pytest.mark.parametrize(
    ("force_remesh", "expected_delete_count"),
    [(True, 1), (False, 0)],
)
def test_mesh_deletion_follows_force_remesh(force_remesh, expected_delete_count):
    xml_text = render_template_xml(make_config(force_remesh=force_remesh))
    root = ET.fromstring(xml_text)

    deletes = [
        command
        for command in root.findall("command")
        if command.get("cmdType") == "delete" and command.get("obj1") == "mesh"
    ]
    assert len(deletes) == expected_delete_count


def test_each_configured_variable_and_result_maps_to_exactly_one_command():
    config = make_config()
    root = ET.fromstring(render_template_xml(config))

    modifies = [
        command
        for command in root.findall("command")
        if command.get("cmdType") == "modify" and command.get("obj1") == "var"
    ]
    exports = [
        command
        for command in root.findall("command")
        if command.get("cmdType") == "export" and command.get("obj1") == "result"
    ]

    assert [command.get("name") for command in modifies] == [
        "Length & Width",
        "Gap",
    ]
    assert [(command.get("name"), command.get("obj2")) for command in exports] == [
        ("Port & S<1>", "port"),
        ("E field <peak>", "obv"),
    ]


def test_validation_reports_wrong_command_attribute_casing():
    config = make_config()
    xml_text = render_template_xml(config).replace("cmdType=", "cmdtype=", 1)

    assert "invalid_attribute_casing" in issue_codes(xml_text, config)


def test_validation_reports_missing_configured_modification():
    config = make_config()
    root = ET.fromstring(render_template_xml(config))
    gap_command = next(
        command
        for command in root.findall("command")
        if command.get("cmdType") == "modify" and command.get("name") == "Gap"
    )
    root.remove(gap_command)
    xml_text = ET.tostring(root, encoding="unicode")

    assert "variable_command_count" in issue_codes(xml_text, config)


def test_validation_reports_variable_initial_value_mismatch():
    config = make_config()
    root = ET.fromstring(render_template_xml(config))
    length_command = next(
        command
        for command in root.findall("command")
        if command.get("cmdType") == "modify"
        and command.get("name") == "Length & Width"
    )
    length_command.set("value", "$FIRST_VALUE")
    xml_text = ET.tostring(root, encoding="unicode")

    assert "variable_value_mismatch" in issue_codes(xml_text, config)


def test_validation_reports_export_file_mismatch():
    config = make_config()
    root = ET.fromstring(render_template_xml(config))
    first_export = next(
        command
        for command in root.findall("command")
        if command.get("cmdType") == "export"
    )
    first_export.set("file", "$PORT_FILE")
    xml_text = ET.tostring(root, encoding="unicode")

    assert "result_file_mismatch" in issue_codes(xml_text, config)


def test_malformed_xml_is_reported_and_inspection_raises_value_error():
    config = make_config()
    malformed = "<script><command></script>"

    with pytest.raises(ValueError, match="XML"):
        inspect_script_xml(malformed)
    assert "malformed_xml" in issue_codes(malformed, config)
