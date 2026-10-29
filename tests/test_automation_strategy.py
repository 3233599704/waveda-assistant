from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.automation.package_builder import ScriptPackage
from raggg.automation.static_validator import validate_generation_config
from raggg.automation import strategy_planner
from raggg.automation.strategy_planner import SweepPlanningError, plan_sweep
from raggg.automation.task_config import build_task_config, task_signature


def make_config(
    *,
    sweep_vars,
    strategy,
    controller="python",
    custom_description="",
):
    return build_task_config(
        package_dir=r"C:\local package",
        waveda_exe=r"D:\Program Files\WavEDA\WavEDA.exe",
        project_file=r"E:\remote project\model.tsp",
        controller=controller,
        sweep_vars=sweep_vars,
        strategy=strategy,
        custom_description=custom_description,
        results=[
            {"name": "Port_S_data_1", "type": "port", "traces": ["S11 dB"]}
        ],
        target_freq=2.45,
        frequency_unit="GHz",
    )


def issue_codes(config):
    return {issue.code for issue in validate_generation_config(config)}


def test_single_variable_explicit_plan_has_deterministic_points_and_endpoints():
    config = make_config(
        sweep_vars={"length": [-1.25, 0.5, 2.0]},
        strategy="explicit_values",
    )

    plan = plan_sweep(config)

    assert plan.point_count == 3
    assert [point.id for point in plan.points] == [
        "p0001_length_m1p25",
        "p0002_length_0p5",
        "p0003_length_2",
    ]
    assert [dict(point.values) for point in plan.points] == [
        {"length": -1.25},
        {"length": 0.5},
        {"length": 2.0},
    ]
    assert [point.id for point in plan.endpoints] == [
        "p0001_length_m1p25",
        "p0003_length_2",
    ]
    assert plan.smoke_point.id == "p0002_length_0p5"


def test_decimal_range_is_inclusive_without_float_drift():
    config = make_config(
        sweep_vars={"gap": {"start": -0.2, "stop": 0.2, "step": 0.1}},
        strategy="range",
    )

    plan = plan_sweep(config)

    assert [dict(point.values) for point in plan.points] == [
        {"gap": -0.2},
        {"gap": -0.1},
        {"gap": 0.0},
        {"gap": 0.1},
        {"gap": 0.2},
    ]


def test_two_variable_plan_uses_cartesian_order_and_estimated_count():
    config = make_config(
        sweep_vars={
            "width": [1.0, 2.0],
            "height": [10.0, 20.0, 30.0],
        },
        strategy="dual_param",
    )

    plan = plan_sweep(config)

    assert plan.point_count == 6
    assert plan.estimated_point_count == 6
    assert [dict(point.values) for point in plan.points] == [
        {"width": 1.0, "height": 10.0},
        {"width": 1.0, "height": 20.0},
        {"width": 1.0, "height": 30.0},
        {"width": 2.0, "height": 10.0},
        {"width": 2.0, "height": 20.0},
        {"width": 2.0, "height": 30.0},
    ]


@pytest.mark.parametrize(
    ("strategy", "sweep_vars", "expected_issue"),
    [
        ("single_param", {"a": [1, 2], "b": [3, 4]}, "single_param_count"),
        ("dual_param", {"a": [1, 2]}, "dual_param_count"),
        (
            "explicit_values",
            {"a": [1], "b": [2], "c": [3]},
            "unsupported_variable_count",
        ),
    ],
)
def test_only_one_or_two_variables_and_strategy_counts_are_allowed(
    strategy, sweep_vars, expected_issue
):
    config = make_config(sweep_vars=sweep_vars, strategy=strategy)

    assert expected_issue in issue_codes(config)
    with pytest.raises(SweepPlanningError):
        plan_sweep(config)


def test_builtin_waveda_sweep_is_explicitly_unavailable():
    config = make_config(
        sweep_vars={"length": [1.0, 2.0]},
        strategy="builtin_sweep",
    )

    assert "builtin_sweep_unavailable" in issue_codes(config)
    with pytest.raises(SweepPlanningError, match="verified project template"):
        plan_sweep(config)


def test_custom_description_must_not_be_empty():
    config = make_config(
        sweep_vars={"length": [1.0, 2.0]},
        strategy="custom",
        custom_description="",
    )

    issues = validate_generation_config(config)

    assert any(
        issue.code == "custom_description_required"
        and "不能为空" in issue.message
        for issue in issues
    )
    with pytest.raises(SweepPlanningError, match="不能为空"):
        plan_sweep(config)


def test_unknown_custom_description_is_rejected_instead_of_running_fixed_scan():
    config = make_config(
        sweep_vars={"length": [1.0, 2.0]},
        strategy="custom",
        custom_description="自动帮我找到最好看的曲线",
    )

    issues = validate_generation_config(config)

    assert any(
        issue.code == "unsupported_custom_strategy"
        and "不支持的自定义策略" in issue.message
        for issue in issues
    )
    with pytest.raises(SweepPlanningError, match="不支持的自定义策略"):
        plan_sweep(config)
    with pytest.raises(ValueError, match="不支持的自定义策略"):
        ScriptPackage(config).generate_files()


@pytest.mark.parametrize(
    "description",
    [
        "先粗扫再细扫",
        "  COARSE-TO-FINE  ",
    ],
)
def test_controlled_coarse_to_fine_descriptions_create_adaptive_plan(
    description,
):
    config = make_config(
        sweep_vars={"length": [1.0, 2.0, 3.0]},
        strategy="custom",
        custom_description=description,
    )

    plan = plan_sweep(config)

    assert validate_generation_config(config) == []
    assert [dict(point.values) for point in plan.points] == [
        {"length": 1.0},
        {"length": 2.0},
        {"length": 3.0},
    ]
    assert plan.adaptive_parameters == {
        "mode": "adaptive_coarse_to_fine",
        "refinement_factor": 5,
        "neighborhood": "adjacent_coarse_interval",
        "exclude_stage1_points": True,
        "selection_metric": {
            "result_type": "port",
            "result_name": "Port_S_data_1",
            "trace": "S11 dB",
            "metric": "target_frequency_value",
            "goal": "minimize",
        },
    }


@pytest.mark.parametrize(
    "description",
    ["只运行固定扫描", "  FIXED SCAN ONLY  "],
)
def test_controlled_fixed_scan_descriptions_remain_deterministic(description):
    config = make_config(
        sweep_vars={"length": [1.0, 2.0]},
        strategy="custom",
        custom_description=description,
    )

    plan = plan_sweep(config)

    assert validate_generation_config(config) == []
    assert plan.adaptive_parameters is None
    assert [dict(point.values) for point in plan.points] == [
        {"length": 1.0},
        {"length": 2.0},
    ]


@pytest.mark.parametrize(
    "description",
    [
        "不要先粗扫再细扫",
        "先粗扫再细扫并删除工程",
        "先粗扫再细扫 fixed scan only",
        "请 coarse-to-fine 扫描",
        "coarse to fine",
        "fixed scan only please",
        "只运行固定扫描，然后再细扫",
    ],
)
def test_custom_description_rejects_negated_mixed_or_extended_whitelist_text(
    description,
):
    config = make_config(
        sweep_vars={"length": [1.0, 2.0]},
        strategy="custom",
        custom_description=description,
    )

    issues = validate_generation_config(config)

    assert any(
        issue.code == "unsupported_custom_strategy"
        and "不支持的自定义策略" in issue.message
        for issue in issues
    )
    with pytest.raises(SweepPlanningError, match="不支持的自定义策略"):
        plan_sweep(config)


@pytest.mark.parametrize("controller", ["python", "matlab"])
def test_adaptive_package_embeds_runtime_stage2_parameters(controller):
    config = make_config(
        sweep_vars={"length": [1.0, 2.0, 3.0]},
        strategy="custom",
        custom_description="先粗扫再细扫",
        controller=controller,
    )

    files = ScriptPackage(config).generate_files()
    packaged = json.loads(files["task_config.json"])

    planned = packaged["sweep"]["planned_points"]
    assert planned["mode"] == "adaptive_coarse_to_fine"
    assert [point["assignments"][0]["value"] for point in planned["stage1_points"]] == [
        1.0,
        2.0,
        3.0,
    ]
    assert planned["stage2"]["refinement_factor"] == 5
    assert planned["stage2"]["neighborhood"] == "adjacent_coarse_interval"
    assert planned["stage2"]["selection_metric"]["metric"] == (
        "target_frequency_value"
    )


@pytest.mark.parametrize(
    "values",
    [
        [1.0],
        [1.0, 1.0, 1.0],
    ],
)
def test_adaptive_coarse_stage_requires_two_distinct_parameter_combinations(
    values,
):
    config = make_config(
        sweep_vars={"length": values},
        strategy="custom",
        custom_description="先粗扫再细扫",
    )

    issues = validate_generation_config(config)

    assert any(
        issue.code == "adaptive_requires_multiple_points"
        and "至少 2 个不同参数组合" in issue.message
        for issue in issues
    )
    with pytest.raises(SweepPlanningError, match="至少 2 个不同参数组合"):
        plan_sweep(config)


@pytest.mark.parametrize("controller", ["python", "matlab"])
def test_package_embeds_one_shared_plan_for_both_controller_languages(controller):
    config = make_config(
        sweep_vars={"length": [-1.25, 0.5]},
        strategy="single_param",
        controller=controller,
    )

    files = ScriptPackage(config).generate_files()
    packaged = json.loads(files["task_config.json"])

    assert packaged["sweep"]["estimated_point_count"] == 2
    assert packaged["sweep"]["endpoint_ids"] == [
        "p0001_length_m1p25",
        "p0002_length_0p5",
    ]
    assert packaged["sweep"]["planned_points"] == [
        {
            "id": "p0001_length_m1p25",
            "assignments": [{"name": "length", "value": -1.25}],
        },
        {
            "id": "p0002_length_0p5",
            "assignments": [{"name": "length", "value": 0.5}],
        },
    ]
    assert packaged["task_signature"] == task_signature(packaged)


@pytest.mark.parametrize(
    "sweep_vars",
    [
        {"length": {"start": 0, "stop": 10_000, "step": 1}},
        {"width": list(range(101)), "gap": list(range(100))},
    ],
)
def test_sweep_plan_rejects_more_than_10000_points_before_expansion(sweep_vars):
    strategy = "range" if len(sweep_vars) == 1 else "dual_param"
    config = make_config(sweep_vars=sweep_vars, strategy=strategy)

    assert strategy_planner.MAX_SWEEP_POINTS == 10_000
    assert "too_many_sweep_points" in issue_codes(config)
    with pytest.raises(SweepPlanningError, match="10,000"):
        plan_sweep(config)


def test_oversized_range_is_rejected_before_range_values_are_materialized(
    monkeypatch,
):
    config = make_config(
        sweep_vars={"length": {"start": 0, "stop": 1e12, "step": 1e-9}},
        strategy="range",
    )

    def fail_if_expanded(_variable):
        raise AssertionError("oversized range must be rejected before expansion")

    monkeypatch.setattr(strategy_planner, "_range_values", fail_if_expanded)

    with pytest.raises(SweepPlanningError, match="10,000"):
        plan_sweep(config)
