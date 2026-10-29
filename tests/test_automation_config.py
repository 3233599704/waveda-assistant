from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.automation.static_validator import validate_generation_config
from raggg.automation.task_config import build_task_config, task_signature


def make_config(**overrides):
    arguments = {
        "package_dir": r"C:\Users\builder\Desktop\WavEDA package",
        "waveda_exe": r"D:\Program Files\WavEDA\WavEDA.exe",
        "project_file": r"E:\remote projects\filter & antenna <v2>.tsp",
        "controller": "matlab",
        "sweep_vars": {
            "length": {"start": 9.0, "stop": 11.0, "step": 0.5},
        },
        "strategy": "range",
        "results": [
            {
                "name": "Port & S<1>",
                "type": "port",
                "traces": ["S11 dB"],
            }
        ],
        "target_freq": 2.4567,
        "frequency_unit": "GHz",
        "timeout_seconds": 900,
        "max_attempts": 2,
        "force_remesh": True,
        "resume": True,
    }
    arguments.update(overrides)
    return build_task_config(**arguments)


def issue_codes(config):
    return {issue.code for issue in validate_generation_config(config)}


def test_remote_windows_paths_are_normalized_without_checking_local_existence(monkeypatch):
    config = make_config()

    def fail_if_called(_self):
        raise AssertionError("generation-time validation must not inspect target paths")

    monkeypatch.setattr(Path, "exists", fail_if_called)

    assert validate_generation_config(config) == []
    assert config["package_dir"] == r"C:\Users\builder\Desktop\WavEDA package"
    assert config["target"]["waveda_exe"] == r"D:\Program Files\WavEDA\WavEDA.exe"
    assert config["target"]["project_file"] == (
        r"E:\remote projects\filter & antenna <v2>.tsp"
    )


def test_missing_sweep_variables_are_rejected():
    config = make_config(sweep_vars={})

    assert "missing_variables" in issue_codes(config)


def test_zero_range_step_is_rejected():
    config = make_config(
        sweep_vars={"length": {"start": 9.0, "stop": 11.0, "step": 0.0}}
    )

    assert "zero_step" in issue_codes(config)


@pytest.mark.parametrize(
    ("strategy", "sweep_vars", "expected_issue"),
    [
        (
            "range",
            {"length": [9.0, 9.5, 10.0]},
            "range_variable_shape",
        ),
        (
            "explicit_values",
            {"length": {"start": 9.0, "stop": 11.0, "step": 0.5}},
            "explicit_values_variable_shape",
        ),
    ],
)
def test_strategy_rejects_the_other_variable_definition_shape(
    strategy, sweep_vars, expected_issue
):
    config = make_config(strategy=strategy, sweep_vars=sweep_vars)

    assert expected_issue in issue_codes(config)


def test_duplicate_variable_names_are_case_insensitive():
    config = make_config(
        sweep_vars={
            "Length": [9.0, 10.0],
            " length ": [11.0, 12.0],
        },
        strategy="explicit_values",
    )

    assert "duplicate_variable" in issue_codes(config)


@pytest.mark.parametrize("controller", ["matlab", "python"])
def test_supported_controller_choice_is_preserved(controller):
    config = make_config(controller=controller)

    assert config["controller"] == controller
    assert "unsupported_controller" not in issue_codes(config)


def test_unsupported_controller_is_rejected():
    config = make_config(controller="both")

    assert "unsupported_controller" in issue_codes(config)


@pytest.mark.parametrize(
    ("argument", "runtime_field", "expected_issue"),
    [
        ("force_remesh", "force_remesh", "invalid_force_remesh"),
        ("resume", "resume", "invalid_resume"),
    ],
)
def test_non_boolean_runtime_flags_are_not_silently_coerced(
    argument, runtime_field, expected_issue
):
    config = make_config(**{argument: "false"})

    assert config["runtime"][runtime_field] == "false"
    assert expected_issue in issue_codes(config)


def test_float_frequency_and_xml_sensitive_values_survive_normalization():
    config = make_config()

    assert config["frequency"] == {"target": 2.4567, "unit": "GHz"}
    assert config["results"][0]["name"] == "Port & S<1>"
    assert config["target"]["project_file"].endswith("filter & antenna <v2>.tsp")
    assert validate_generation_config(config) == []


def test_explicit_data_frequency_unit_is_normalized_and_validated():
    config = make_config(data_frequency_unit="MHz")

    assert config["data_frequency_unit"] == "MHz"
    assert "invalid_data_frequency_unit" not in issue_codes(config)

    invalid = make_config(data_frequency_unit="cycles")
    assert "invalid_data_frequency_unit" in issue_codes(invalid)


@pytest.mark.parametrize(
    "traces",
    [[], [""], ["   "], [1], "S11 dB"],
)
def test_result_traces_must_be_a_nonempty_list_of_nonempty_strings(traces):
    config = make_config(
        results=[
            {
                "name": "Port_S_data_1",
                "type": "port",
                "traces": traces,
            }
        ]
    )

    assert "invalid_result_traces" in issue_codes(config)


def test_multiple_named_port_traces_are_preserved():
    config = make_config(
        results=[
            {
                "name": "Port_S_data_1",
                "type": "port",
                "traces": ["S11 dB", "S21 dB"],
            }
        ]
    )

    assert config["results"][0]["traces"] == ["S11 dB", "S21 dB"]
    assert "invalid_result_traces" not in issue_codes(config)


def test_task_signature_is_stable_and_ignores_local_package_destination():
    first = make_config()
    reordered = copy.deepcopy(first)
    reordered["target"] = {
        "project_file": first["target"]["project_file"],
        "waveda_exe": first["target"]["waveda_exe"],
    }
    relocated = copy.deepcopy(first)
    relocated["package_dir"] = r"C:\another local output"

    assert task_signature(first) == task_signature(reordered)
    assert task_signature(first) == task_signature(relocated)

    changed = copy.deepcopy(first)
    changed["sweep"]["variables"][0]["step"] = 0.25
    assert task_signature(first) != task_signature(changed)


def test_task_signature_covers_derived_plan_fields_when_present():
    first = make_config()
    first["sweep"]["planned_points"] = [
        {
            "id": "p0001_length_9",
            "assignments": [{"name": "length", "value": 9.0}],
        }
    ]
    first["sweep"]["endpoint_ids"] = ["p0001_length_9"]
    first["sweep"]["estimated_point_count"] = 1

    changed_point = copy.deepcopy(first)
    changed_point["sweep"]["planned_points"][0]["id"] = "p0001_tampered"
    changed_endpoint = copy.deepcopy(first)
    changed_endpoint["sweep"]["endpoint_ids"] = ["p0001_tampered"]

    assert task_signature(first) != task_signature(changed_point)
    assert task_signature(first) != task_signature(changed_endpoint)
