from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.automation.package_builder import ScriptPackage
from raggg.automation.task_config import build_task_config


def render_controller(
    *,
    observer=False,
    strategy="explicit_values",
    custom_description="",
):
    results = [
        {"name": "Port_S_data_1", "type": "port", "traces": ["S11 dB"]}
    ]
    if observer:
        results.append(
            {"name": "Observer_E_1", "type": "obv", "traces": ["E magnitude"]}
        )
    config = build_task_config(
        package_dir=r"C:\local package",
        waveda_exe=r"D:\Program Files\WavEDA\WavEDA.exe",
        project_file=r"E:\remote project\model.tsp",
        controller="matlab",
        sweep_vars={"length": [1.0, 2.0, 3.0]},
        strategy=strategy,
        custom_description=custom_description,
        results=results,
        timeout_seconds=47,
        max_attempts=4,
        target_freq=2450.0,
        frequency_unit="MHz",
        resume=True,
    )
    return ScriptPackage(config).generate_files()["run_batch.m"]


def test_matlab_adaptive_controller_selects_best_then_runs_stage2_points():
    source = render_controller(
        strategy="custom",
        custom_description="coarse-to-fine",
    )

    assert "function point = select_adaptive_best_point(" in source
    assert "function points = build_adaptive_stage2_points(" in source
    run_sweep = source.split("function summary = run_sweep", 1)[1].split(
        "function analysis = analyze_results", 1
    )[0]
    assert run_sweep.index("analysis = analyze_results(") < run_sweep.index(
        "select_adaptive_best_point("
    )
    assert run_sweep.index("select_adaptive_best_point(") < run_sweep.index(
        "build_adaptive_stage2_points("
    )
    assert '"adaptive"' in run_sweep
    assert "if isempty(adaptive_points)" in run_sweep
    assert 'error("Adaptive stage 2 produced no new points.")' in run_sweep


def local_function_names(source):
    return set(
        re.findall(
            r"(?m)^function(?:\s+\[[^\]]+\]|\s+\w+)?\s*=?\s*(\w+)\s*\(",
            source,
        )
    )


def test_controller_discovers_package_and_loads_json_relative_to_it():
    source = render_controller()

    assert "package_dir = fileparts(mfilename('fullpath'))" in source
    assert "fullfile(package_dir, 'task_config.json')" in source
    assert "jsondecode(fileread(config_path))" in source
    assert "cd(" not in source


def test_default_and_explicit_modes_have_check_smoke_run_dispatch():
    source = render_controller()

    assert "function exit_code = run_batch(mode)" in source
    assert 'mode = "auto"' in source
    assert 'case "auto"' in source
    assert 'case "check"' in source
    assert 'case "smoke"' in source
    assert 'case "run"' in source
    auto_case = source.split('case "auto"', 1)[1].split('case "check"', 1)[0]
    dispatch = source.split("function config = load_config", 1)[0]
    assert dispatch.index("issues = preflight_check(") < dispatch.index(
        'case "auto"'
    )
    assert auto_case.index("run_smoke(") < auto_case.index("run_sweep(")


def test_required_controller_functions_are_present():
    source = render_controller()

    assert {
        "run_batch",
        "load_config",
        "preflight_check",
        "prepare_directories",
        "generate_point_xml",
        "run_waveda",
        "validate_result",
        "save_progress",
        "analyze_results",
        "build_report",
    } <= local_function_names(source)


def test_runtime_timeout_retry_and_process_termination_are_config_driven():
    source = render_controller()

    assert "config.runtime.timeout_seconds" in source
    assert "config.runtime.max_attempts" in source
    assert "elapsed = toc(started)" in source
    assert "elapsed > timeout_seconds" in source
    assert "fprintf(bat_id, 'cd /d \"%s\"\\r\\n', waveda_dir)" in source


def test_waveda_receives_script_argument_from_its_install_directory():
    source = render_controller()

    assert "waveda_dir, waveda_name" in source
    assert '"script=%s"' in source
    assert "cd /d" in source


def test_parse_tsp_xml_strips_trailing_content_before_xml_parsing():
    source = render_controller()

    assert "function document = parse_tsp_xml(tsp_path)" in source
    assert "fileread(tsp_path)" in source
    assert "last XML closing tag" in source
    assert "close_ends(end)" in source
    assert "ByteArrayInputStream" in source
    assert "parse_tsp_xml(config.target.project_file)" in source


def test_preflight_read_only_parses_tsp_variables_and_typed_results():
    source = render_controller()

    preflight = source.split("function issues = preflight_check", 1)[1].split(
        "function paths = prepare_directories", 1
    )[0]
    assert "parse_tsp_xml(config.target.project_file)" in preflight
    assert "'variables'" in preflight
    assert "'port-results'" in preflight
    assert "'obv-results'" in preflight
    assert "'expression'" in preflight
    assert "xmlwrite(config.target.project_file" not in source


def test_tsp_data_frequency_unit_is_required_and_converted_to_hz():
    source = render_controller()

    assert "project-unit" in source
    assert "data_frequency_unit" in source
    assert "frequency_multiplier" in source
    assert "frequency_hz" in source
    assert "Data frequency unit is missing" in source


def test_each_attempt_deletes_old_outputs_then_validates_numeric_fresh_data():
    source = render_controller()

    assert "delete(result_paths{result_index})" in source
    assert "dir(result_path)" in source
    assert "readmatrix(result_path" in source
    assert "isfinite(data(:))" in source
    assert "~isempty(data)" in source
    assert "datenum" in source


def test_result_validation_has_distinct_port_and_observer_contracts():
    source = render_controller()
    validation = source.split(
        "function [valid, message, data] = validate_result", 1
    )[1].split("function progress_path = save_progress", 1)[0]

    assert 'result_type == "port"' in validation
    assert "size(data, 1) < 2" in validation
    assert "all(diff(trace.frequency_hz) > 0)" in validation
    assert "all(trace.values == 0)" in validation
    assert "trace_count" in validation
    assert "target_hz" in validation
    assert 'result_type == "obv"' in validation


def test_matlab_port_parser_structures_shared_paired_and_stacked_traces():
    source = render_controller()

    assert "function traces = parse_port_traces" in source
    assert 'layout = "shared"' in source
    assert 'layout = "paired"' in source
    assert 'layout = "stacked"' in source
    assert "trace.frequency_hz" in source
    assert "all(diff(trace.frequency_hz) > 0)" in source


def test_progress_and_resume_require_matching_task_signature():
    source = render_controller()

    assert "'progress.csv'" in source
    assert "writetable(" in source
    assert "config.task_signature" in source
    assert "strcmp(progress.task_signature, string(config.task_signature))" in source
    assert "result_files_json" in source


def test_matlab_preflight_rejects_edited_config_with_stale_task_signature():
    source = render_controller()
    preflight = source.split("function issues = preflight_check", 1)[1].split(
        "function names = collect_result_names", 1
    )[0]

    assert "verify_task_signature(config)" in preflight
    assert "function valid = verify_task_signature(config)" in source
    assert "config.task_signature_payload" in source
    assert "jsondecode(config.task_signature_payload)" in source
    # SHA-256 match + valid JSON is sufficient; no deep comparison needed
    assert "sha256_text(payload_text)" in source
    assert "MessageDigest.getInstance('SHA-256')" in source
    assert "Task signature does not match task_config.json." in source


def test_matlab_preflight_rebuilds_signed_plan_and_endpoint_ids():
    source = render_controller()
    preflight = source.split("function issues = preflight_check", 1)[1].split(
        "function names = collect_result_names", 1
    )[0]

    assert "validate_plan_integrity(config)" in preflight
    assert "function issues = validate_plan_integrity(config)" in source
    assert "rebuild_plan_points(config)" in source
    assert "endpoint_ids do not match the deterministic sweep plan" in source
    assert "estimated_point_count does not match" in source


def test_matlab_runtime_replan_checks_10000_limit_before_expansion():
    source = render_controller()
    rebuild = source.split("function points = rebuild_plan_points", 1)[1].split(
        "function point_id = validate_point_id", 1
    )[0]

    assert "estimate_sweep_point_count(config)" in rebuild
    assert "function point_count = estimate_sweep_point_count(config)" in source
    assert "max_sweep_points = 10000" in source
    assert rebuild.index("estimate_sweep_point_count(config)") < rebuild.index(
        "value_sets ="
    )


def test_matlab_point_paths_validate_ids_and_use_canonical_confinement():
    source = render_controller()

    assert "function point_id = validate_point_id(raw_point_id)" in source
    assert "^[A-Za-z0-9_.-]+$" in source
    assert "contains(point_id, '..')" in source
    assert "function path = confined_path(root_path, relative_path)" in source
    assert "getCanonicalPath()" in source
    assert "point_raw = confined_path(paths.raw, point.id)" in source
    assert (
        "xml_path = confined_path(paths.generated_xml, "
        "char(point.id) + \".xml\")"
    ) in source
    assert "log_path = confined_path(paths.logs" in source


def test_matlab_preflight_checks_template_hash_and_structured_commands():
    source = render_controller()
    preflight = source.split("function issues = preflight_check", 1)[1].split(
        "function names = collect_result_names", 1
    )[0]

    assert "validate_template_integrity(config, paths)" in preflight
    assert "function issues = validate_template_integrity(config, paths)" in source
    assert "sha256_file(template_path)" in source
    assert "config.integrity.template_xml_sha256" in source
    assert "xmlread(template_path)" in source
    assert "project_load_count = count_commands(commands, \"load\", \"project\")" in source
    assert "project path does not match config" in source
    assert "variable command does not match config" in source
    assert "result export does not match config" in source
    assert "remesh command does not match config" in source


def test_resume_uses_tsp_content_sha256_runtime_signature_and_session_cache():
    source = render_controller()

    assert "function signature = build_runtime_signature(config)" in source
    assert "project_sha256 = sha256_file(config.target.project_file)" in source
    assert "project_sha256" in source
    assert "runtime_signature" in source
    assert "session_results" in source
    assert "~ismember(" in source
    assert '"runtime_signature", string(progress.Properties.VariableNames)' in source
    assert "numel(result_paths) == numel(config.results)" in source


def test_matlab_process_drains_stdout_and_stderr_via_batch_redirect_with_timeout():
    source = render_controller()
    runner = source.split(
        "function [return_code, stdout_text, stderr_text] =", 1
    )[1].split(
        "function [valid, message, data] = validate_result", 1
    )[0]

    assert "fopen(bat_path, 'w')" in runner
    assert "fprintf(bat_id, 'cd /d" in runner
    assert '"script=%s"' in runner
    assert "2>&1" in runner
    assert "elapsed = toc(started)" in runner
    assert "elapsed > timeout_seconds" in runner
    assert "stdout_text" in runner
    assert "stderr_text" in runner
    assert "System.Diagnostics.Process" not in runner
    assert "StringBuilder" not in runner


def test_analysis_filters_port_results_and_keeps_per_point_metrics():
    source = render_controller()
    analysis = source.split("function analysis = analyze_results", 1)[1].split(
        "function report_path = build_report", 1
    )[0]

    assert 'result_type ~= "port"' in analysis
    assert "continue" in analysis
    assert "analysis.points." in analysis
    assert "config.results(result_index).name" in analysis
    assert "parse_port_traces(" in analysis
    assert "metrics.traces." in analysis


def test_auto_validates_configured_endpoints_before_full_sweep():
    source = render_controller()
    dispatch = source.split("function config = load_config", 1)[0]

    assert "validate_endpoints(" in dispatch
    assert dispatch.index("validate_endpoints(") < dispatch.index("run_sweep(")
    assert "config.sweep.endpoint_ids" in source
    assert "result_matrices_differ" in source


def test_matlab_endpoints_support_observer_only_and_tolerant_matrix_difference():
    source = render_controller(observer=True)
    endpoints = source.split(
        "function [endpoint_ok, message] = validate_endpoints", 1
    )[1].split("function summary = run_sweep", 1)[0]

    assert "load_result_matrices(" in endpoints
    assert "result_matrices_differ(" in endpoints
    assert "absolute_tolerance" in endpoints
    assert "relative_tolerance" in endpoints
    assert "no valid port result" not in endpoints.lower()
    assert "has_port_results(config)" in source


def test_smoke_uses_nonbaseline_point_and_full_run_can_reuse_it():
    source = render_controller()

    run_smoke = source.split("function smoke_ok = run_smoke", 1)[1].split(
        "function summary = run_sweep", 1
    )[0]
    run_sweep = source.split("function summary = run_sweep", 1)[1]
    selector = source.split("function point = select_smoke_point", 1)[1].split(
        "function summary = run_sweep", 1
    )[0]
    assert "point = select_smoke_point(points)" in run_smoke
    assert "jsonencode(points(1).assignments)" in selector
    assert "jsonencode(points(candidate_index).assignments)" in selector
    assert "points(2)" not in run_smoke
    assert run_smoke.index("reusable_result(") < run_smoke.index("run_waveda(")
    assert run_sweep.index("reusable_result(") < run_sweep.index("run_waveda(")


def test_matlab_smoke_catches_planning_generation_launch_and_validation_errors():
    source = render_controller()
    run_smoke = source.split("function smoke_ok = run_smoke", 1)[1].split(
        "function point = select_smoke_point", 1
    )[0]

    assert run_smoke.index("try") < run_smoke.index("select_smoke_point(points)")
    assert "catch smoke_error" in run_smoke
    catch_block = run_smoke.split("catch smoke_error", 1)[1]
    assert "smoke_ok = false" in catch_block
    assert "[smoke]" in catch_block


def test_point_failure_is_recorded_and_loop_continues():
    source = render_controller()

    run_sweep = source.split("function summary = run_sweep", 1)[1]
    assert "for point_index = 1:numel(points)" in run_sweep
    assert "save_progress(" in run_sweep
    assert "continue" in run_sweep
    assert "failed_points" in run_sweep


def test_each_matlab_point_catches_generation_launch_and_validation_exceptions():
    source = render_controller()
    run_sweep = source.split("function summary = run_sweep", 1)[1].split(
        "function analysis = analyze_results", 1
    )[0]

    loop = run_sweep.split("for point_index = 1:numel(points)", 1)[1]
    assert loop.index("try") < loop.index("reusable_result(")
    assert "catch point_error" in loop
    catch_block = loop.split("catch point_error", 1)[1]
    assert "save_progress(" in catch_block
    assert "failed_points" in catch_block
    assert "continue" in catch_block


def test_observer_disabled_controller_never_references_optional_arrays():
    source = render_controller(observer=False)

    assert "all_e_max" not in source
    assert "all_e_max_time" not in source
    assert "observer_values" not in source
