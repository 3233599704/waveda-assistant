"""Minimal ZIP package assembly for portable WavEDA automation."""

from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from raggg.automation.renderers.xml_renderer import (
    render_template_xml,
    validate_template_xml,
)
from raggg.automation.renderers.python_renderer import render_python_controller
from raggg.automation.renderers.matlab_renderer import render_matlab_controller
from raggg.automation.static_validator import validate_generation_config
from raggg.automation.strategy_planner import SweepPlanningError, plan_sweep
from raggg.automation.task_config import task_signature, task_signature_payload
from raggg.automation.template_sentinels import find_template_sentinel

README_NAME = "README_运行说明.md"


class PackageBuildError(ValueError):
    """Raised when generated package content fails a pre-write check."""


def _collect_config_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, Mapping):
        strings: set[str] = set()
        for nested_value in value.values():
            strings.update(_collect_config_strings(nested_value))
        return strings
    if isinstance(value, (list, tuple)):
        strings = set()
        for nested_value in value:
            strings.update(_collect_config_strings(nested_value))
        return strings
    return set()


def _build_readme(config: Mapping[str, Any]) -> str:
    controller = str(config["controller"])
    controller_file = "run_batch.m" if controller == "matlab" else "run_batch.py"
    if controller == "matlab":
        default_command = "`run_batch`"
        step_commands = (
            "`run_batch(\"check\")`、`run_batch(\"smoke\")`、"
            "`run_batch(\"run\")`"
        )
    else:
        default_command = "`python run_batch.py`"
        step_commands = (
            "`python run_batch.py --check-only`、"
            "`python run_batch.py --smoke-only`、"
            "`python run_batch.py --run-only`"
        )
    return f"""# WavEDA 便携扫参任务包

本包在本地电脑生成，可复制并解压到目标电脑的任意目录。

- 控制器：{controller.upper()}
- 入口文件：`{controller_file}`
- WavEDA 工程：外部路径 `{config["target"]["project_file"]}`
- `.tsp` 工程不会复制到压缩包中。
- 结果保存在压缩包解压目录内。

默认运行会自动执行 `check -> smoke -> endpoint -> run`：{default_command}。

需要排查时可分步运行：{step_commands}。

目标电脑必须存在配置中指定的 `.tsp` 工程和 WavEDA 可执行文件；
控制器只读检查 `.tsp`，不会修改或打包该工程。
"""


class ScriptPackage:
    """Generate and write the exact four-file portable package manifest."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        controller_renderer: Callable[[Mapping[str, Any]], str] | None = None,
    ) -> None:
        self.config = copy.deepcopy(dict(config))
        self._controller_renderer = controller_renderer

    def _packaged_config(self, template_xml_sha256: str) -> dict[str, Any]:
        packaged = copy.deepcopy(self.config)
        packaged.pop("package_dir", None)
        try:
            plan = plan_sweep(self.config)
        except SweepPlanningError as exc:
            raise PackageBuildError(f"Invalid sweep strategy: {exc}") from exc
        packaged_sweep = packaged["sweep"]
        stage1_points = [point.to_dict() for point in plan.points]
        if plan.adaptive_parameters is None:
            packaged_sweep["planned_points"] = stage1_points
        else:
            adaptive = copy.deepcopy(plan.adaptive_parameters)
            mode = adaptive.pop("mode")
            packaged_sweep["planned_points"] = {
                "mode": mode,
                "stage1_points": stage1_points,
                "stage2": adaptive,
            }
        packaged_sweep["estimated_point_count"] = plan.estimated_point_count
        packaged_sweep["endpoint_ids"] = [
            point.id for point in plan.endpoints
        ]
        packaged["integrity"] = {
            "template_xml_sha256": template_xml_sha256,
        }
        packaged["task_signature"] = task_signature(packaged)
        packaged["task_signature_payload"] = task_signature_payload(packaged)
        return packaged

    def _render_controller(self, packaged_config: Mapping[str, Any]) -> tuple[str, str]:
        controller = str(self.config.get("controller", ""))
        if controller == "python":
            renderer = self._controller_renderer or render_python_controller
            return "run_batch.py", renderer(packaged_config)
        if controller == "matlab":
            renderer = self._controller_renderer or render_matlab_controller
            return "run_batch.m", renderer(packaged_config)
        raise PackageBuildError("控制器只能选择 MATLAB 或 Python。")

    def _check_controller_sentinels(
        self, controller_name: str, controller_text: str
    ) -> None:
        content_without_user_data = controller_text
        user_strings = {
            value
            for value in _collect_config_strings(self.config)
            if find_template_sentinel(value) is not None
        }
        for value in sorted(user_strings, key=len, reverse=True):
            content_without_user_data = content_without_user_data.replace(value, "")
            json_encoded = json.dumps(value, ensure_ascii=False)[1:-1]
            content_without_user_data = content_without_user_data.replace(
                json_encoded, ""
            )
        if find_template_sentinel(content_without_user_data) is not None:
            raise PackageBuildError(
                f"{controller_name} 中存在未替换的占位符。"
            )

    def generate_files(self) -> dict[str, str]:
        """Render and validate all files before returning package content."""

        config_issues = validate_generation_config(self.config)
        if config_issues:
            details = "；".join(issue.message for issue in config_issues)
            raise PackageBuildError(f"任务配置无效：{details}")

        xml_text = render_template_xml(self.config)
        xml_issues = validate_template_xml(xml_text, self.config)
        if xml_issues:
            details = "；".join(issue.message for issue in xml_issues)
            raise PackageBuildError(f"template.xml 校验失败：{details}")
        template_xml_sha256 = hashlib.sha256(
            xml_text.encode("utf-8")
        ).hexdigest()

        packaged_config = self._packaged_config(template_xml_sha256)
        config_json = json.dumps(
            packaged_config,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        try:
            if json.loads(config_json) != packaged_config:
                raise PackageBuildError("task_config.json 往返校验失败。")
        except json.JSONDecodeError as exc:
            raise PackageBuildError(f"task_config.json 生成失败：{exc}") from exc

        controller_name, controller_text = self._render_controller(packaged_config)
        files = {
            README_NAME: _build_readme(packaged_config),
            "task_config.json": f"{config_json}\n",
            "template.xml": xml_text,
            controller_name: controller_text,
        }
        self._check_controller_sentinels(controller_name, controller_text)

        if controller_name == "run_batch.py":
            try:
                compile(controller_text, controller_name, "exec")
            except SyntaxError as exc:
                raise PackageBuildError(
                    f"生成的 Python 控制器语法无效：{exc.msg}"
                ) from exc

        return files

    def write_zip(self, destination: str | Path) -> Path:
        """Write a validated ZIP and return its resolved destination path."""

        destination_path = Path(destination)
        if destination_path.suffix.lower() != ".zip":
            destination_path = destination_path / "waveda_script_package.zip"
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        files = self.generate_files()
        with zipfile.ZipFile(
            destination_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for name, content in files.items():
                archive.writestr(name, content.encode("utf-8"))
        return destination_path
