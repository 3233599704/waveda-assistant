from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from raggg.automation import (
    ScriptPackage as AutomationScriptPackage,
    build_task_config as automation_build_task_config,
)
from raggg.config import Settings
from raggg.desktop.script_generator_dialog import ScriptGeneratorDialog
from raggg.generation.script_generator import (
    ScriptPackage as LegacyScriptPackage,
    build_task_config as legacy_build_task_config,
)
from raggg.theme import set_theme


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app, tmp_path):
    settings = Settings(
        project_root=tmp_path,
        waveda_root=None,
        waveda_help_root=tmp_path / "wavEDA_docs",
        waveda_example_root=None,
        obsidian_vault_root=tmp_path / "knowledge_base",
        data_dir=tmp_path / "data",
        embedding_model="local-hashed-vectors",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="",
        llm_model="deepseek-chat",
    )
    widget = ScriptGeneratorDialog(settings)
    widget.zip_path_edit.setText(str(tmp_path / "waveda_sweep.zip"))
    widget.exe_edit.setText(r"D:\Program Files\WavEDA\WavEDA.exe")
    widget.tsp_edit.setText(r"E:\remote projects\antenna.tsp")
    first = widget._var_rows[0]
    first["name"].setText("length")
    first["start"].setText("9")
    first["stop"].setText("11")
    first["step"].setText("0.5")
    yield widget
    widget.close()


def _texts(widget, widget_type):
    return [child.text() for child in widget.findChildren(widget_type)]


@pytest.mark.parametrize(
    ("theme", "expected_background", "expected_text"),
    [
        ("light", "#f7fbfd", "#10202d"),
        ("dark", "#23344b", "#dce5f0"),
    ],
)
def test_standard_context_menu_uses_application_theme_outside_settings_dialog(
    app,
    dialog,
    theme,
    expected_background,
    expected_text,
):
    original_style = app.styleSheet()
    try:
        with patch("raggg.theme._current_theme", "light"), patch(
            "raggg.theme._save_theme",
        ):
            set_theme(theme)
            menu = dialog.zip_path_edit.createStandardContextMenu()
            menu.ensurePolished()

            assert menu.palette().color(QPalette.Window).name() == expected_background
            assert menu.palette().color(QPalette.Text).name() == expected_text
            menu.close()
    finally:
        app.setStyleSheet(original_style)


def test_paths_distinguish_local_zip_from_remote_target_and_remove_work_dir(dialog):
    labels = _texts(dialog, QLabel)

    assert "本地 ZIP 保存位置：" in labels
    assert "异地电脑 WavEDA.exe 路径：" in labels
    assert "异地电脑外部 .tsp 路径：" in labels
    assert not hasattr(dialog, "work_edit")
    assert dialog.zip_path_edit.text().endswith(".zip")


def test_controller_is_single_language_and_builtin_sweep_is_disabled(dialog):
    controllers = [
        dialog.controller_combo.itemData(index)
        for index in range(dialog.controller_combo.count())
    ]
    assert controllers == ["matlab", "python"]

    builtin_index = dialog.strategy_combo.findData("builtin_sweep")
    assert builtin_index >= 0
    assert not dialog.strategy_combo.model().item(builtin_index).isEnabled()
    assert "暂未支持" in dialog.strategy_combo.itemText(builtin_index)


def test_frequency_accepts_decimals_and_has_explicit_unit(dialog):
    assert isinstance(dialog.target_freq_spin, QDoubleSpinBox)
    assert dialog.target_freq_spin.decimals() >= 3
    units = [
        dialog.frequency_unit_combo.itemData(index)
        for index in range(dialog.frequency_unit_combo.count())
    ]
    assert units == ["Hz", "kHz", "MHz", "GHz"]

    dialog.target_freq_spin.setValue(2.4567)
    dialog.frequency_unit_combo.setCurrentIndex(
        dialog.frequency_unit_combo.findData("GHz")
    )
    config = dialog.collect_config()

    assert config["frequency"] == {"target": 2.4567, "unit": "GHz"}


def test_port_traces_and_export_data_frequency_unit_are_user_configurable(dialog):
    dialog.port_traces_edit.setText("S11 dB, S21 dB")
    data_units = [
        dialog.data_frequency_unit_combo.itemData(index)
        for index in range(dialog.data_frequency_unit_combo.count())
    ]

    assert data_units == [None, "Hz", "kHz", "MHz", "GHz"]
    automatic = dialog.collect_config()
    assert automatic["results"][0]["traces"] == ["S11 dB", "S21 dB"]
    assert "data_frequency_unit" not in automatic

    dialog.data_frequency_unit_combo.setCurrentIndex(
        dialog.data_frequency_unit_combo.findData("MHz")
    )
    explicit = dialog.collect_config()
    assert explicit["data_frequency_unit"] == "MHz"


def test_ui_reports_oversized_scan_before_preview_or_generation(dialog):
    first = dialog._var_rows[0]
    first["start"].setText("0")
    first["stop"].setText("10000")
    first["step"].setText("1")

    issues = dialog.check_configuration(show_message=False)

    assert any(
        issue.code == "too_many_sweep_points"
        and "10,000" in issue.message
        for issue in issues
    )


def test_range_and_explicit_value_rows_generate_normalized_strategy(dialog):
    config = dialog.collect_config()
    assert config["sweep"]["strategy"] == "range"
    assert config["sweep"]["variables"] == [
        {"name": "length", "start": 9.0, "stop": 11.0, "step": 0.5}
    ]

    first = dialog._var_rows[0]
    first["values"].setText("9, 10.5, 12")
    explicit = dialog.collect_config()

    assert explicit["sweep"]["strategy"] == "explicit_values"
    assert explicit["sweep"]["variables"] == [
        {"name": "length", "values": [9.0, 10.5, 12.0]}
    ]


def test_mixed_two_variable_formats_use_dual_parameter_strategy(dialog):
    first = dialog._var_rows[0]
    first["values"].setText("9, 10")
    dialog._add_variable_row()
    second = dialog._var_rows[1]
    second["name"].setText("gap")
    second["start"].setText("0.2")
    second["stop"].setText("0.4")
    second["step"].setText("0.1")

    config = dialog.collect_config()

    assert config["sweep"]["strategy"] == "dual_param"
    assert config["sweep"]["variables"] == [
        {"name": "length", "values": [9.0, 10.0]},
        {"name": "gap", "start": 0.2, "stop": 0.4, "step": 0.1},
    ]


def test_custom_strategy_reveals_description_and_writes_it_to_config(dialog, app):
    custom_index = dialog.strategy_combo.findData("custom")
    dialog.strategy_combo.setCurrentIndex(custom_index)
    app.processEvents()

    assert not dialog.custom_description_edit.isHidden()
    dialog.custom_description_edit.setPlainText("先粗扫再细扫")

    config = dialog.collect_config()

    assert config["sweep"]["strategy"] == "custom"
    assert config["sweep"]["custom_description"] == "先粗扫再细扫"


def test_custom_ui_lists_supported_controlled_descriptions(dialog):
    help_text = dialog.custom_supported_label.text()

    assert "先粗扫再细扫" in help_text
    assert "coarse-to-fine" in help_text
    assert "只运行固定扫描" in help_text
    assert "fixed scan only" in help_text
    assert "其他描述会被拒绝" in help_text


@pytest.mark.parametrize(
    ("description", "expected_code", "expected_message"),
    [
        ("", "custom_description_required", "不能为空"),
        (
            "自动帮我选择任何你觉得好的策略",
            "unsupported_custom_strategy",
            "不支持的自定义策略",
        ),
    ],
)
def test_custom_ui_validation_fails_closed(
    dialog, description, expected_code, expected_message
):
    dialog.strategy_combo.setCurrentIndex(
        dialog.strategy_combo.findData("custom")
    )
    dialog.custom_description_edit.setPlainText(description)

    issues = dialog.check_configuration(show_message=False)

    assert any(
        issue.code == expected_code and expected_message in issue.message
        for issue in issues
    )


def test_runtime_controls_are_preserved_in_config(dialog):
    dialog.remesh_check.setChecked(False)
    dialog.timeout_spin.setValue(1234)
    dialog.max_attempts_spin.setValue(4)
    dialog.resume_check.setChecked(False)

    config = dialog.collect_config()

    assert config["runtime"] == {
        "timeout_seconds": 1234.0,
        "max_attempts": 4.0,
        "force_remesh": False,
        "resume": False,
    }


def test_check_configuration_never_probes_remote_path_existence(
    dialog, monkeypatch
):
    def fail_if_called(_self):
        raise AssertionError("本地配置检查不能访问异地路径")

    monkeypatch.setattr(Path, "exists", fail_if_called)

    assert dialog.check_configuration(show_message=False) == []


def test_check_configuration_generates_all_package_content_in_memory(
    dialog, monkeypatch
):
    calls = []
    original = AutomationScriptPackage.generate_files

    def recording_generate_files(package):
        calls.append(package.config)
        return original(package)

    monkeypatch.setattr(
        AutomationScriptPackage,
        "generate_files",
        recording_generate_files,
    )
    destination = Path(dialog.zip_path_edit.text())

    assert dialog.check_configuration(show_message=False) == []
    assert len(calls) == 1
    assert not destination.exists()


@pytest.mark.parametrize(
    ("controller", "included", "excluded"),
    [
        ("matlab", "run_batch.m", "run_batch.py"),
        ("python", "run_batch.py", "run_batch.m"),
    ],
)
def test_generate_zip_contains_only_selected_controller_and_no_tsp(
    dialog, tmp_path, controller, included, excluded
):
    destination = tmp_path / f"{controller}_sweep.zip"
    dialog.zip_path_edit.setText(str(destination))
    dialog.controller_combo.setCurrentIndex(
        dialog.controller_combo.findData(controller)
    )

    written = dialog.generate_package()

    assert written == destination
    with zipfile.ZipFile(written) as archive:
        names = set(archive.namelist())
    assert names == {
        "README_运行说明.md",
        "task_config.json",
        "template.xml",
        included,
    }
    assert excluded not in names
    assert not any(name.lower().endswith(".tsp") for name in names)


def test_preview_text_matches_exact_package_manifest(dialog):
    dialog.controller_combo.setCurrentIndex(
        dialog.controller_combo.findData("python")
    )

    preview = dialog.preview_text()

    assert "本地 ZIP 保存位置：" in preview
    assert "压缩包内共 4 个文件：" in preview
    assert "README_运行说明.md" in preview
    assert "task_config.json" in preview
    assert "template.xml" in preview
    assert "run_batch.py" in preview
    assert "run_batch.m" not in preview
    assert "不会包含外部 .tsp 工程文件" in preview
    assert "check → smoke → endpoint → run" in preview


def test_buttons_use_clear_chinese_labels_without_mojibake(dialog):
    assert dialog.windowTitle() == "WavEDA 自动脚本生成器"
    button_texts = _texts(dialog, QPushButton)
    assert "检查配置" in button_texts
    assert "预览压缩包清单" in button_texts
    assert "生成压缩包" in button_texts

    visible_text = "\n".join(
        _texts(dialog, QLabel)
        + button_texts
        + [
            dialog.windowTitle(),
            dialog.exe_edit.placeholderText(),
            dialog.tsp_edit.placeholderText(),
            dialog.zip_path_edit.placeholderText(),
        ]
    )
    for mojibake_fragment in ("�", "鍙", "鐢", "璺", "绠"):
        assert mojibake_fragment not in visible_text


def test_small_screen_keeps_generation_buttons_visible_and_clickable(
    dialog, app, monkeypatch
):
    assert dialog.minimumHeight() <= 560
    dialog.resize(760, 540)
    dialog.show()
    app.processEvents()

    for button in (
        dialog.check_button,
        dialog.preview_button,
        dialog.generate_zip_button,
    ):
        top_left = button.mapTo(dialog, QPoint(0, 0))
        bottom_right = top_left + QPoint(button.width() - 1, button.height() - 1)
        assert button.isVisible()
        assert button.isEnabled()
        assert dialog.rect().contains(top_left)
        assert dialog.rect().contains(bottom_right)

    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args: messages.append(args) or QMessageBox.Ok,
    )
    dialog.generate_zip_button.click()
    app.processEvents()

    assert Path(dialog.zip_path_edit.text()).is_file()
    assert messages


def test_legacy_generator_module_is_a_compatibility_reexport():
    assert LegacyScriptPackage is AutomationScriptPackage
    assert legacy_build_task_config is automation_build_task_config
