from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.automation.package_builder import ScriptPackage
from raggg.automation.task_config import build_task_config


def tsp_xml(
    results,
    *,
    variable_name="length",
    variable_expression="1.0",
    project_frequency_unit="Hz",
):
    result_nodes = []
    for result in results:
        if result["type"] == "port":
            result_nodes.append(
                "<port-result "
                f'name="{result["name"]}">'
                '<port/><xlabel name="Frequency" unit="2"/>'
                '<handle option="S(1,1)" format="dB"/>'
                "</port-result>"
            )
        else:
            result_nodes.append(
                "<obv-result "
                f'name="{result["name"]}">'
                '<obv obvtype="0" axis="Y"/>'
                '<xlabel name="Time" unit="1"/>'
                '<handle obvComp="Ex" format="none"/>'
                "</obv-result>"
            )
    port_nodes = "".join(
        node for node in result_nodes if node.startswith("<port-result")
    )
    observer_nodes = "".join(
        node for node in result_nodes if node.startswith("<obv-result")
    )
    project_unit = (
        f'<project-unit freq="{project_frequency_unit}"/>'
        if project_frequency_unit is not None
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<project version="2.2" type="EM">'
        f"{project_unit}"
        "<variables>"
        f'<var name="{variable_name}" expression="{variable_expression}" '
        f'origin="{variable_expression}"/>'
        "</variables>"
        "<result-display><em-results>"
        f"<obv-results>{observer_nodes}</obv-results>"
        f"<port-results>{port_nodes}</port-results>"
        "</em-results></result-display>"
        "</project>"
    )


def make_package(
    tmp_path: Path,
    *,
    values=(1.0, 2.0, 3.0),
    max_attempts=2,
    timeout_seconds=17,
    resume=True,
    target_freq=2.45,
    frequency_unit="GHz",
    results=None,
    project_frequency_unit="Hz",
    data_frequency_unit=None,
    strategy="explicit_values",
    custom_description="",
):
    package_dir = tmp_path / "copied package"
    package_dir.mkdir()
    waveda_exe = tmp_path / "target machine" / "WavEDA.exe"
    project_file = tmp_path / "target machine" / "model.tsp"
    waveda_exe.parent.mkdir()
    waveda_exe.write_bytes(b"fake executable")
    if results is None:
        results = [
            {"name": "Port_S_data_1", "type": "port", "traces": ["S11 dB"]}
        ]
    project_file.write_text(
        tsp_xml(results, project_frequency_unit=project_frequency_unit),
        encoding="utf-8",
    )
    config = build_task_config(
        package_dir=str(package_dir),
        waveda_exe=str(waveda_exe),
        project_file=str(project_file),
        controller="python",
        sweep_vars={"length": list(values)},
        strategy=strategy,
        custom_description=custom_description,
        results=results,
        target_freq=target_freq,
        frequency_unit=frequency_unit,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        force_remesh=True,
        resume=resume,
    )
    if data_frequency_unit is not None:
        config["data_frequency_unit"] = data_frequency_unit
    for name, content in ScriptPackage(config).generate_files().items():
        (package_dir / name).write_bytes(content.encode("utf-8"))
    spec = importlib.util.spec_from_file_location(
        f"generated_run_batch_{time.time_ns()}",
        package_dir / "run_batch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, package_dir


def install_fake_waveda(
    module,
    *,
    fail_values=(),
    identical_port_data=False,
    frequency_values=(2.40e9, 2.45e9, 2.50e9),
    point_variation=1.0,
):
    calls = []
    attempts_by_value = {}
    fail_values = {float(value) for value in fail_values}

    def fake_run(command, *, cwd, timeout, capture_output, text, check):
        xml_argument = str(command[-1])
        xml_path = Path(
            xml_argument.split("=", 1)[1]
            if xml_argument.startswith("script=")
            else xml_argument
        )
        root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
        modify = root.find("./command[@cmdType='modify']")
        assert modify is not None
        value = float(modify.get("value"))
        attempts_by_value[value] = attempts_by_value.get(value, 0) + 1
        calls.append(
            {
                "value": value,
                "timeout": timeout,
                "cwd": Path(cwd),
                "command": command,
            }
        )
        if value not in fail_values:
            for export in root.findall("./command[@cmdType='export']"):
                result_path = Path(export.get("file"))
                result_path.parent.mkdir(parents=True, exist_ok=True)
                middle_value = (
                    -11.0
                    if identical_port_data
                    else -10.0 - value * point_variation
                )
                result_path.write_text(
                    "frequency value\n"
                    f"{frequency_values[0]} -8.0\n"
                    f"{frequency_values[1]} {middle_value}\n"
                    f"{frequency_values[2]} -7.0\n",
                    encoding="utf-8",
                )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    module.subprocess.run = fake_run
    return calls, attempts_by_value


def read_progress(package_dir: Path):
    with (package_dir / "output" / "progress.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def test_preflight_rebuilds_and_rejects_tampered_derived_plan(tmp_path):
    module, _package_dir = make_package(tmp_path)
    config = module.load_config()
    config["sweep"]["planned_points"][0]["id"] = "p0001_tampered"
    config["sweep"]["endpoint_ids"] = ["p0001_tampered"]
    config["task_signature"] = module._task_signature(config)

    issues = module.preflight_check(config)

    assert any("deterministic sweep plan" in issue for issue in issues)
    assert any("endpoint_ids" in issue for issue in issues)


def test_runtime_replan_rejects_oversized_range_before_materializing_values(
    tmp_path, monkeypatch
):
    module, _package_dir = make_package(tmp_path)
    config = module.load_config()
    config["sweep"]["variables"] = [
        {"name": "length", "start": 0.0, "stop": 10_000.0, "step": 1.0}
    ]
    config["sweep"]["strategy"] = "range"
    config["task_signature"] = module._task_signature(config)

    def fail_if_materialized(_variable):
        raise AssertionError("oversized runtime plan must not be expanded")

    monkeypatch.setattr(module, "_variable_values", fail_if_materialized)

    issues = module.preflight_check(config)

    assert any("10,000" in issue for issue in issues)


@pytest.mark.parametrize(
    "unsafe_id",
    ["../escaped", "..\\escaped", "nested/point", "nested\\point", "point id"],
)
def test_point_derived_paths_reject_unsafe_point_ids(tmp_path, unsafe_id):
    module, package_dir = make_package(tmp_path)
    config = module.load_config()
    point = {
        "id": unsafe_id,
        "assignments": [{"name": "length", "value": 1.0}],
    }

    with pytest.raises(ValueError, match="point ID"):
        module.generate_point_xml(config, point, package_dir)


def test_attempt_log_path_is_confined_to_logs_directory(tmp_path):
    module, package_dir = make_package(tmp_path)
    paths = module.prepare_directories(package_dir)
    completed = SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(ValueError, match="point ID"):
        module._write_attempt_log(paths, "../../escaped", 1, completed)


def test_preflight_rejects_template_sha256_mismatch(tmp_path):
    module, package_dir = make_package(tmp_path)
    config = module.load_config()
    template_path = package_dir / "template.xml"
    original = template_path.read_text(encoding="utf-8")
    config.setdefault("integrity", {})["template_xml_sha256"] = hashlib.sha256(
        original.encode("utf-8")
    ).hexdigest()
    config["task_signature"] = module._task_signature(config)
    template_path.write_text(original.replace("solver=\"auto\"", "solver=\"bad\""))

    issues = module.preflight_check(config)

    assert any("SHA-256" in issue for issue in issues)


@pytest.mark.parametrize(
    "mutation",
    [
        "project_path",
        "variable_name",
        "variable_value",
        "result_name",
        "result_type",
        "result_file",
        "remesh",
    ],
)
def test_preflight_structurally_rejects_tampered_template_even_with_new_hash(
    tmp_path, mutation
):
    module, package_dir = make_package(tmp_path)
    config = module.load_config()
    template_path = package_dir / "template.xml"
    root = ET.fromstring(template_path.read_text(encoding="utf-8"))
    if mutation == "project_path":
        root.find("./command[@cmdType='load']").set("file", r"Z:\wrong.tsp")
    elif mutation == "variable_name":
        root.find("./command[@cmdType='modify']").set("name", "wrong")
    elif mutation == "variable_value":
        root.find("./command[@cmdType='modify']").set("value", "999")
    elif mutation == "result_name":
        root.find("./command[@cmdType='export']").set("name", "wrong")
    elif mutation == "result_type":
        root.find("./command[@cmdType='export']").set("obj2", "obv")
    elif mutation == "result_file":
        root.find("./command[@cmdType='export']").set("file", "../../wrong.txt")
    else:
        root.remove(root.find("./command[@cmdType='delete']"))
    ET.indent(root, space="    ")
    changed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"{ET.tostring(root, encoding='unicode', short_empty_elements=True)}\n"
    )
    template_path.write_text(changed, encoding="utf-8")
    config.setdefault("integrity", {})["template_xml_sha256"] = hashlib.sha256(
        changed.encode("utf-8")
    ).hexdigest()
    config["task_signature"] = module._task_signature(config)

    issues = module.preflight_check(config)

    assert any("template.xml structure" in issue for issue in issues)


def test_adaptive_controller_runs_coarse_stage_then_refines_near_best_port_point(
    tmp_path,
):
    module, package_dir = make_package(
        tmp_path,
        values=(1.0, 2.0, 3.0),
        strategy="custom",
        custom_description="先粗扫再细扫",
    )
    calls, _attempts = install_fake_waveda(module)

    exit_code = module.main(["--run-only"])

    assert exit_code == 0
    called_values = [round(call["value"], 10) for call in calls]
    assert set(called_values) == {1.0, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0}
    assert called_values.index(3.0) < called_values.index(2.2)

    report = json.loads(
        (package_dir / "output" / "report.json").read_text(encoding="utf-8")
    )
    assert report["completed_point_count"] == 7
    adaptive_points = {
        point_id: metrics
        for point_id, metrics in report["analysis"]["points"].items()
        if point_id.startswith("a")
    }
    assert len(adaptive_points) == 4

    progress = read_progress(package_dir)
    assert {row["stage"] for row in progress if row["point_id"].startswith("a")} == {
        "adaptive"
    }


def test_adaptive_runtime_fails_explicitly_when_stage2_has_no_new_points(
    tmp_path, capsys
):
    module, _package_dir = make_package(
        tmp_path,
        values=(1.0, 2.0),
        strategy="custom",
        custom_description="先粗扫再细扫",
    )
    install_fake_waveda(module)
    module.build_adaptive_stage2_points = lambda _config, _best: []

    exit_code = module.main(["--run-only"])

    assert exit_code != 0
    assert "Adaptive stage 2 produced no new points." in capsys.readouterr().out


def test_generated_controller_loads_config_relative_to_its_own_file(tmp_path):
    module, package_dir = make_package(tmp_path)

    old_cwd = Path.cwd()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        os.chdir(elsewhere)
        config = module.load_config()
        paths = module.prepare_directories()
    finally:
        os.chdir(old_cwd)

    assert config["target"]["project_file"].endswith("model.tsp")
    assert paths["package"] == package_dir
    assert paths["raw"] == package_dir / "output" / "raw"
    assert paths["logs"] == package_dir / "output" / "logs"
    assert paths["figures"] == package_dir / "output" / "figures"


def test_target_files_are_checked_only_when_generated_controller_runs(tmp_path):
    module, package_dir = make_package(tmp_path)
    config_path = package_dir / "task_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    Path(config["target"]["project_file"]).unlink()

    issues = module.preflight_check(config)

    assert any("project" in issue.lower() or ".tsp" in issue.lower() for issue in issues)


def test_preflight_read_only_inspects_real_tsp_variable_and_result_schema(tmp_path):
    results = [
        {"name": "Port_S_data_1", "type": "port", "traces": ["S11 dB"]},
        {"name": "Observer_E_1", "type": "obv", "traces": ["Ex"]},
    ]
    module, _package_dir = make_package(tmp_path, results=results)
    config = module.load_config()
    project_path = Path(config["target"]["project_file"])
    before = project_path.read_bytes()

    issues = module.preflight_check(config)

    assert issues == []
    assert project_path.read_bytes() == before


def test_preflight_rejects_missing_or_expression_sweep_variable(tmp_path):
    module, _package_dir = make_package(tmp_path)
    config = module.load_config()
    project_path = Path(config["target"]["project_file"])

    project_path.write_text(
        tsp_xml(config["results"], variable_name="other"),
        encoding="utf-8",
    )
    missing_issues = module.preflight_check(config)
    assert any("length" in issue and "variable" in issue.lower() for issue in missing_issues)

    project_path.write_text(
        tsp_xml(
            config["results"],
            variable_name="length",
            variable_expression="base_length * 2",
        ),
        encoding="utf-8",
    )
    expression_issues = module.preflight_check(config)
    assert any("expression" in issue.lower() for issue in expression_issues)


def test_preflight_rejects_missing_or_wrong_type_result_node(tmp_path):
    module, _package_dir = make_package(tmp_path)
    config = module.load_config()
    project_path = Path(config["target"]["project_file"])

    project_path.write_text(
        tsp_xml(
            [{"name": "Other_Port", "type": "port", "traces": ["S11 dB"]}]
        ),
        encoding="utf-8",
    )
    missing_issues = module.preflight_check(config)
    assert any("Port_S_data_1" in issue for issue in missing_issues)

    project_path.write_text(
        tsp_xml(
            [{"name": "Port_S_data_1", "type": "obv", "traces": ["Ex"]}]
        ),
        encoding="utf-8",
    )
    wrong_type_issues = module.preflight_check(config)
    assert any("type" in issue.lower() for issue in wrong_type_issues)


def test_preflight_fails_closed_when_tsp_format_is_unrecognized(tmp_path):
    module, _package_dir = make_package(tmp_path)
    config = module.load_config()
    project_path = Path(config["target"]["project_file"])
    project_path.write_text("not a WavEDA XML project", encoding="utf-8")

    issues = module.preflight_check(config)

    assert any(
        "unrecognized" in issue.lower() or "parse" in issue.lower()
        for issue in issues
    )


def test_tsp_project_frequency_unit_converts_real_ghz_export_to_hz(tmp_path):
    module, package_dir = make_package(
        tmp_path,
        project_frequency_unit="GHz",
    )
    install_fake_waveda(
        module,
        frequency_values=(1.0, 2.45, 3.0),
    )

    assert module.main(["--run-only"]) == 0
    report = json.loads(
        (package_dir / "output" / "report.json").read_text(encoding="utf-8")
    )
    assert report["analysis"]["nearest_frequency_hz"] == 2.45e9
    assert report["analysis"]["resonance_frequency_hz"] == 2.45e9


def test_preflight_rejects_missing_data_frequency_unit_without_override(
    tmp_path,
):
    module, _package_dir = make_package(
        tmp_path,
        project_frequency_unit=None,
    )

    issues = module.preflight_check(module.load_config())

    assert any("data frequency unit" in issue.lower() for issue in issues)


def test_explicit_data_frequency_unit_is_used_when_tsp_unit_is_missing(
    tmp_path,
):
    module, package_dir = make_package(
        tmp_path,
        project_frequency_unit=None,
        data_frequency_unit="GHz",
    )
    install_fake_waveda(
        module,
        frequency_values=(1.0, 2.45, 3.0),
    )

    assert module.main(["--run-only"]) == 0
    report = json.loads(
        (package_dir / "output" / "report.json").read_text(encoding="utf-8")
    )
    assert report["analysis"]["nearest_frequency_hz"] == 2.45e9


@pytest.mark.parametrize(
    ("contents", "age_seconds", "expected"),
    [
        ("1.0e9 -10\n", 0, True),
        ("", 0, False),
        ("header only\n", 0, False),
        ("1.0e9 NaN\n", 0, False),
        ("1.0e9 Infinity\n", 0, False),
        ("1.0e9 broken\n", 0, False),
        ("1.0e9 -10\n", 10, False),
    ],
)
def test_result_validation_requires_fresh_finite_nonempty_numeric_data(
    tmp_path, contents, age_seconds, expected
):
    module, _ = make_package(tmp_path)
    result = tmp_path / "result.txt"
    result.write_text(contents, encoding="utf-8")
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(result, (old, old))

    valid, _message, rows = module.validate_result(result, time.time() - 1)

    assert valid is expected
    assert bool(rows) is expected


@pytest.mark.parametrize(
    ("contents", "traces", "target", "expected"),
    [
        ("2.40e9 -8\n2.50e9 -10\n", ["S11 dB"], 2.45, True),
        ("2.45e9 -10\n", ["S11 dB"], 2.45, False),
        ("2.50e9 -8\n2.40e9 -10\n", ["S11 dB"], 2.45, False),
        ("2.40e9 0\n2.50e9 0\n", ["S11 dB"], 2.45, False),
        ("2.40e9 -8\n2.50e9 -10\n", ["S11 dB", "S21 dB"], 2.45, False),
        ("2.40e9 -8\n2.50e9 -10\n", ["S11 dB"], 3.00, False),
    ],
)
def test_port_validation_enforces_sweep_and_trace_contract(
    tmp_path, contents, traces, target, expected
):
    module, _ = make_package(tmp_path)
    result = tmp_path / "port.txt"
    result.write_text(contents, encoding="utf-8")

    valid, _message, _rows = module.validate_result(
        result,
        time.time() - 1,
        {"name": "Port_S_data_1", "type": "port", "traces": traces},
        {"target": target, "unit": "GHz"},
        "Hz",
    )

    assert valid is expected


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            [
                [1.0, -10.0, -20.0],
                [2.0, -11.0, -21.0],
                [3.0, -9.0, -19.0],
            ],
            [
                {
                    "frequency_hz": [1.0e9, 2.0e9, 3.0e9],
                    "values": [-10.0, -11.0, -9.0],
                },
                {
                    "frequency_hz": [1.0e9, 2.0e9, 3.0e9],
                    "values": [-20.0, -21.0, -19.0],
                },
            ],
        ),
        (
            [
                [1.0, -10.0, 1.0, -20.0],
                [2.0, -11.0, 2.0, -21.0],
                [3.0, -9.0, 3.0, -19.0],
            ],
            [
                {
                    "frequency_hz": [1.0e9, 2.0e9, 3.0e9],
                    "values": [-10.0, -11.0, -9.0],
                },
                {
                    "frequency_hz": [1.0e9, 2.0e9, 3.0e9],
                    "values": [-20.0, -21.0, -19.0],
                },
            ],
        ),
        (
            [
                [1.0, -10.0],
                [2.0, -11.0],
                [3.0, -9.0],
                [1.0, -20.0],
                [2.0, -21.0],
                [3.0, -19.0],
            ],
            [
                {
                    "frequency_hz": [1.0e9, 2.0e9, 3.0e9],
                    "values": [-10.0, -11.0, -9.0],
                },
                {
                    "frequency_hz": [1.0e9, 2.0e9, 3.0e9],
                    "values": [-20.0, -21.0, -19.0],
                },
            ],
        ),
    ],
)
def test_port_parser_structures_shared_paired_and_stacked_layouts(
    tmp_path, rows, expected
):
    module, _ = make_package(tmp_path)

    assert module.parse_port_traces(rows, 2, "GHz") == expected


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (
            "1 -10 1 -20\n2.45 -11 2.45 -21\n3 -9 3 -19\n",
            True,
        ),
        (
            "1 -10\n2.45 -11\n3 -9\n"
            "1 -20\n2.45 -21\n3 -19\n",
            True,
        ),
        (
            "1 -10 4 -20\n2.45 -11 5 -21\n3 -9 6 -19\n",
            False,
        ),
        (
            "1 -10 1 -20\n2.45 -11 3 -21\n3 -9 2 -19\n",
            False,
        ),
    ],
)
def test_port_validation_checks_each_trace_frequency_contract(
    tmp_path, contents, expected
):
    module, _ = make_package(tmp_path)
    result = tmp_path / "multi_trace_port.txt"
    result.write_text(contents, encoding="utf-8")

    valid, _message, traces = module.validate_result(
        result,
        time.time() - 1,
        {
            "name": "Port_S_data_1",
            "type": "port",
            "traces": ["S11 dB", "S21 dB"],
        },
        {"target": 2.45, "unit": "GHz"},
        "GHz",
    )

    assert valid is expected
    assert bool(traces) is expected


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ("1.25\n", True),
        ("0 0 0\n", True),
        ("NaN\n", False),
        ("", False),
    ],
)
def test_observer_validation_uses_nonempty_finite_rule(
    tmp_path, contents, expected
):
    module, _ = make_package(tmp_path)
    result = tmp_path / "observer.txt"
    result.write_text(contents, encoding="utf-8")

    valid, _message, _rows = module.validate_result(
        result,
        time.time() - 1,
        {"name": "Observer_E_1", "type": "obv", "traces": ["Ex"]},
        {"target": 2.45, "unit": "GHz"},
    )

    assert valid is expected


def test_default_mode_runs_check_smoke_run_and_reuses_nonbaseline_smoke(tmp_path):
    module, package_dir = make_package(tmp_path)
    calls, _attempts = install_fake_waveda(module)

    exit_code = module.main([])

    assert exit_code == 0
    assert [call["value"] for call in calls] == [2.0, 1.0, 3.0]
    assert all(call["timeout"] == 17 for call in calls)
    expected_waveda_dir = Path(module.load_config()["target"]["waveda_exe"]).parent
    assert all(call["cwd"] == expected_waveda_dir for call in calls)
    assert all(
        str(call["command"][-1]).startswith("script=") for call in calls
    )
    rows = read_progress(package_dir)
    completed = [row for row in rows if row["status"] == "completed"]
    assert {row["point_id"] for row in completed} == {
        "p0001_length_1",
        "p0002_length_2",
        "p0003_length_3",
    }


def test_modes_can_be_run_individually(tmp_path):
    module, package_dir = make_package(tmp_path)
    calls, _attempts = install_fake_waveda(module)

    assert module.main(["--check-only"]) == 0
    assert calls == []
    assert module.main(["--smoke-only"]) == 0
    assert [call["value"] for call in calls] == [2.0]
    assert module.main(["--run-only"]) == 0
    assert [call["value"] for call in calls] == [2.0, 1.0, 3.0]
    assert (package_dir / "output" / "report.json").is_file()


def test_run_only_allows_a_single_point_but_automatic_smoke_rejects_it(tmp_path):
    module, _package_dir = make_package(tmp_path, values=(1.0,))
    calls, _attempts = install_fake_waveda(module)

    assert module.main(["--run-only"]) == 0
    assert [call["value"] for call in calls] == [1.0]

    calls.clear()
    assert module.main([]) != 0
    assert calls == []


def test_old_output_is_deleted_before_each_attempt_and_cannot_fake_success(
    tmp_path,
):
    module, package_dir = make_package(
        tmp_path, values=(1.0, 2.0), max_attempts=2
    )
    paths = module.prepare_directories()
    stale = paths["raw"] / "p0002_length_2" / "result_01_port.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("2.45e9 -99\n", encoding="utf-8")
    calls, attempts = install_fake_waveda(module, fail_values={2.0})

    exit_code = module.main(["--smoke-only"])

    assert exit_code != 0
    assert not stale.exists()
    assert attempts[2.0] == 2
    assert len(calls) == 2


def test_failed_point_does_not_stop_later_points(tmp_path):
    module, package_dir = make_package(tmp_path, max_attempts=1)
    calls, _attempts = install_fake_waveda(module, fail_values={2.0})

    exit_code = module.main(["--run-only"])

    assert exit_code != 0
    assert [call["value"] for call in calls] == [1.0, 3.0, 2.0]
    rows = read_progress(package_dir)
    latest = {row["point_id"]: row["status"] for row in rows}
    assert latest["p0002_length_2"] == "failed"
    assert latest["p0003_length_3"] == "completed"


def test_resume_reuses_only_matching_signature_and_valid_results(tmp_path):
    module, package_dir = make_package(tmp_path, values=(1.0, 2.0))
    calls, _attempts = install_fake_waveda(module)
    assert module.main(["--run-only"]) == 0
    assert len(calls) == 2

    calls.clear()
    assert module.main(["--run-only"]) == 0
    assert calls == []

    progress_path = package_dir / "output" / "progress.csv"
    rows = read_progress(package_dir)
    for row in rows:
        row["task_signature"] = "different-task"
    with progress_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    assert module.main(["--run-only"]) == 0
    assert [call["value"] for call in calls] == [1.0, 2.0]


def test_resume_runtime_signature_detects_tsp_content_change(tmp_path):
    module, package_dir = make_package(tmp_path, values=(1.0, 2.0))
    calls, _attempts = install_fake_waveda(module)
    assert module.main(["--run-only"]) == 0
    assert len(calls) == 2

    project_path = Path(module.load_config()["target"]["project_file"])
    original_stat = project_path.stat()
    changed = project_path.read_text(encoding="utf-8").replace(
        'expression="1.0"', 'expression="2.0"'
    ).replace('origin="1.0"', 'origin="2.0"')
    project_path.write_text(changed, encoding="utf-8")
    assert project_path.stat().st_size == original_stat.st_size
    os.utime(
        project_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )

    calls.clear()
    assert module.main(["--run-only"]) == 0
    assert [call["value"] for call in calls] == [1.0, 2.0]
    rows = read_progress(package_dir)
    assert all(row["runtime_signature"] for row in rows)


def test_resume_false_still_reuses_smoke_inside_same_invocation(tmp_path):
    module, _package_dir = make_package(tmp_path, resume=False)
    calls, _attempts = install_fake_waveda(module)

    assert module.main([]) == 0

    assert [call["value"] for call in calls] == [2.0, 1.0, 3.0]


def test_auto_endpoint_validation_rejects_identical_port_curves(tmp_path):
    module, package_dir = make_package(tmp_path)
    calls, _attempts = install_fake_waveda(
        module, identical_port_data=True
    )

    exit_code = module.main([])

    assert exit_code != 0
    assert [call["value"] for call in calls] == [2.0, 1.0, 3.0]
    assert not (package_dir / "output" / "report.json").exists()


def test_observer_only_endpoints_use_result_matrices_and_can_run(tmp_path):
    results = [
        {"name": "Observer_E_1", "type": "obv", "traces": ["Ex"]}
    ]
    module, package_dir = make_package(tmp_path, results=results)
    calls, _attempts = install_fake_waveda(module)

    assert module.main(["--run-only"]) == 0
    assert [call["value"] for call in calls] == [1.0, 3.0, 2.0]
    assert (package_dir / "output" / "report.json").is_file()


def test_observer_only_does_not_require_a_project_frequency_unit(tmp_path):
    results = [
        {"name": "Observer_E_1", "type": "obv", "traces": ["Ex"]}
    ]
    module, _package_dir = make_package(
        tmp_path,
        results=results,
        project_frequency_unit=None,
    )
    install_fake_waveda(module)

    assert module.main(["--run-only"]) == 0


def test_endpoint_difference_uses_relative_and_absolute_tolerance(tmp_path):
    module, package_dir = make_package(tmp_path)
    calls, _attempts = install_fake_waveda(
        module,
        point_variation=1.0e-12,
    )

    assert module.main(["--run-only"]) != 0
    assert [call["value"] for call in calls] == [1.0, 3.0]
    assert not (package_dir / "output" / "report.json").exists()


def test_result_matrix_difference_treats_float_noise_as_equal(tmp_path):
    module, _package_dir = make_package(tmp_path)
    first = [[[1.0, -10.0], [2.0, -20.0]]]
    noisy = [[[1.0 + 1e-12, -10.0 - 1e-10], [2.0, -20.0]]]
    changed = [[[1.0, -10.0], [2.0, -19.0]]]

    assert not module.result_matrices_differ(
        first,
        noisy,
        absolute_tolerance=1e-9,
        relative_tolerance=1e-9,
    )
    assert module.result_matrices_differ(
        first,
        changed,
        absolute_tolerance=1e-9,
        relative_tolerance=1e-9,
    )


def test_smoke_endpoint_is_reused_before_batch_and_other_endpoint_is_staged(
    tmp_path,
):
    module, package_dir = make_package(tmp_path, values=(1.0, 2.0))
    calls, _attempts = install_fake_waveda(module)

    assert module.main([]) == 0

    assert [call["value"] for call in calls] == [2.0, 1.0]
    rows = read_progress(package_dir)
    stages = {row["point_id"]: row["stage"] for row in rows}
    assert stages == {
        "p0001_length_1": "endpoint",
        "p0002_length_2": "smoke",
    }


@pytest.mark.parametrize(
    ("unit", "target", "expected_hz"),
    [("Hz", 2.45e9, 2.45e9), ("MHz", 2450, 2.45e9), ("GHz", 2.45, 2.45e9)],
)
def test_analysis_converts_configured_target_frequency_to_hz(
    tmp_path, unit, target, expected_hz
):
    module, package_dir = make_package(
        tmp_path,
        values=(1.0, 2.0),
        target_freq=target,
        frequency_unit=unit,
    )
    result = package_dir / "result.txt"
    result.write_text("2.40e9 -8\n2.45e9 -12\n2.50e9 -7\n", encoding="utf-8")

    analysis = module.analyze_results(
        module.load_config(), {"point": [str(result)]}
    )

    assert analysis["target_frequency_hz"] == expected_hz
    assert analysis["nearest_frequency_hz"] == 2.45e9


def test_analysis_uses_only_port_results_and_reports_each_successful_point(
    tmp_path,
):
    results = [
        {"name": "Observer_E_1", "type": "obv", "traces": ["Ex"]},
        {"name": "Port_S_data_1", "type": "port", "traces": ["S11 dB"]},
    ]
    module, package_dir = make_package(tmp_path, results=results)
    files_by_point = {}
    for point_id, minimum in (("p1", -11.0), ("p2", -22.0)):
        observer = package_dir / f"{point_id}_observer.txt"
        observer.write_text("0 999\n1 888\n", encoding="utf-8")
        port = package_dir / f"{point_id}_port.txt"
        port.write_text(
            f"2.40e9 -8\n2.45e9 {minimum}\n2.50e9 -7\n",
            encoding="utf-8",
        )
        files_by_point[point_id] = [str(observer), str(port)]

    analysis = module.analyze_results(module.load_config(), files_by_point)

    assert set(analysis["points"]) == {"p1", "p2"}
    assert analysis["points"]["p1"]["ports"]["Port_S_data_1"][
        "resonance_value"
    ] == -11.0
    assert analysis["points"]["p2"]["ports"]["Port_S_data_1"][
        "resonance_value"
    ] == -22.0
    assert "Observer_E_1" not in analysis["points"]["p1"]["ports"]


def test_analysis_reports_each_port_trace_from_paired_layout_in_hz(tmp_path):
    results = [
        {
            "name": "Port_S_data_1",
            "type": "port",
            "traces": ["S11 dB", "S21 dB"],
        }
    ]
    module, package_dir = make_package(
        tmp_path,
        results=results,
        project_frequency_unit="GHz",
    )
    port = package_dir / "paired_port.txt"
    port.write_text(
        "1 -8 1 -3\n2.45 -15 2.45 -1\n3 -7 3 -4\n",
        encoding="utf-8",
    )

    analysis = module.analyze_results(
        module.load_config(),
        {"p1": [str(port)]},
    )

    traces = analysis["points"]["p1"]["ports"]["Port_S_data_1"]["traces"]
    assert traces["S11 dB"]["resonance_frequency_hz"] == 2.45e9
    assert traces["S21 dB"]["resonance_frequency_hz"] == 3.0e9
