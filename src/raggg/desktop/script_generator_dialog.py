"""WavEDA 便携自动脚本任务包生成窗口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QDoubleSpinBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from raggg.automation import (
    PackageBuildError,
    ScriptPackage,
    ValidationIssue,
    build_task_config,
    validate_generation_config,
)
from raggg.automation.custom_strategy import SUPPORTED_CUSTOM_DESCRIPTIONS
from raggg.config import Settings
from raggg.i18n import get_text
from raggg.theme import get_colors

COLORS = get_colors()


class ScriptGeneratorDialog(QDialog):
    """Collect a portable sweep task and write a language-specific ZIP."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._var_rows: list[dict[str, QWidget]] = []
        self.setWindowTitle(get_text("script_gen_title"))
        self.setMinimumSize(720, 540)
        self._build_ui()

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        description = QLabel(get_text("script_gen_desc"))
        description.setWordWrap(True)
        description.setStyleSheet(
            f"color:{COLORS['muted']}; font-size:12px;"
        )
        layout.addWidget(description)

        layout.addWidget(self._build_path_group())
        layout.addWidget(self._build_sweep_group())
        layout.addWidget(self._build_result_group())
        layout.addWidget(self._build_runtime_group())
        layout.addStretch()

        button_row = QHBoxLayout()
        self.check_button = QPushButton(get_text("script_gen_check"))
        self.check_button.clicked.connect(self._check_clicked)
        button_row.addWidget(self.check_button)
        button_row.addStretch()

        self.preview_button = QPushButton(get_text("script_gen_preview"))
        self.preview_button.clicked.connect(self._preview)
        button_row.addWidget(self.preview_button)

        self.generate_zip_button = QPushButton(get_text("script_gen_generate"))
        self.generate_zip_button.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['accent']}; color: white; "
            "padding: 8px 24px; font-weight: bold; border-radius: 4px; }}"
        )
        self.generate_zip_button.clicked.connect(self._generate)
        button_row.addWidget(self.generate_zip_button)
        outer_layout.addLayout(button_row)

    def _build_path_group(self) -> QGroupBox:
        group = QGroupBox(get_text("script_gen_path_group"))
        form = QFormLayout(group)
        form.setSpacing(8)

        self.zip_path_edit = QLineEdit()
        self.zip_path_edit.setPlaceholderText(get_text("script_gen_zip_placeholder"))
        zip_button = QPushButton(get_text("script_gen_browse"))
        zip_button.clicked.connect(self._browse_zip_path)
        form.addRow(
            get_text("script_gen_zip_path"),
            self._line_with_button(self.zip_path_edit, zip_button),
        )

        self.exe_edit = QLineEdit()
        self.exe_edit.setPlaceholderText(get_text("script_gen_exe_placeholder"))
        exe_button = QPushButton(get_text("script_gen_browse_local"))
        exe_button.clicked.connect(
            lambda: self._browse_file(
                self.exe_edit, get_text("script_gen_select_exe")
            )
        )
        form.addRow(
            get_text("script_gen_exe_path"),
            self._line_with_button(self.exe_edit, exe_button),
        )

        self.tsp_edit = QLineEdit()
        self.tsp_edit.setPlaceholderText(get_text("script_gen_tsp_placeholder"))
        tsp_button = QPushButton(get_text("script_gen_browse_local"))
        tsp_button.clicked.connect(
            lambda: self._browse_file(
                self.tsp_edit, get_text("script_gen_select_tsp")
            )
        )
        form.addRow(
            get_text("script_gen_tsp_path"),
            self._line_with_button(self.tsp_edit, tsp_button),
        )

        note = QLabel(get_text("script_gen_zip_note"))
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{COLORS['muted']};")
        form.addRow("", note)
        return group

    @staticmethod
    def _line_with_button(edit: QLineEdit, button: QPushButton) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, stretch=1)
        row.addWidget(button)
        return container

    def _build_sweep_group(self) -> QGroupBox:
        group = QGroupBox(get_text("script_gen_sweep_group"))
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self._var_container = QVBoxLayout()
        layout.addLayout(self._var_container)
        self._add_variable_row()

        self.add_variable_button = QPushButton(get_text("script_gen_add_var"))
        self.add_variable_button.clicked.connect(self._add_variable_row)
        layout.addWidget(self.add_variable_button)

        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel(get_text("script_gen_strategy_label")))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem(
            get_text("script_gen_strategy_auto"), "auto_external"
        )
        self.strategy_combo.addItem(get_text("script_gen_strategy_custom"), "custom")
        self.strategy_combo.addItem(
            get_text("script_gen_strategy_builtin"), "builtin_sweep"
        )
        model = self.strategy_combo.model()
        if isinstance(model, QStandardItemModel):
            model.item(self.strategy_combo.count() - 1).setEnabled(False)
        self.strategy_combo.currentIndexChanged.connect(
            self._update_strategy_widgets
        )
        strategy_row.addWidget(self.strategy_combo, stretch=1)
        layout.addLayout(strategy_row)

        self.custom_description_label = QLabel(get_text("script_gen_custom_label"))
        self.custom_description_edit = QPlainTextEdit()
        self.custom_description_edit.setPlaceholderText(get_text("script_gen_custom_placeholder"))
        self.custom_description_edit.setMaximumHeight(90)
        self.custom_supported_label = QLabel(
            get_text("script_gen_custom_hint")
            + "；".join(SUPPORTED_CUSTOM_DESCRIPTIONS)
            + get_text("script_gen_custom_suffix")
        )
        self.custom_supported_label.setWordWrap(True)
        self.custom_supported_label.setStyleSheet(
            f"color:{COLORS['muted']}; font-size:12px;"
        )
        layout.addWidget(self.custom_description_label)
        layout.addWidget(self.custom_description_edit)
        layout.addWidget(self.custom_supported_label)
        self._update_strategy_widgets()
        return group

    def _add_variable_row(self) -> None:
        if len(self._var_rows) >= 2:
            return

        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText(get_text("script_gen_var_name_ph"))
        name_edit.setMaximumWidth(120)
        row.addWidget(QLabel(get_text("script_gen_var_name")))
        row.addWidget(name_edit)

        start_edit = QLineEdit("0")
        start_edit.setMaximumWidth(70)
        row.addWidget(QLabel(get_text("script_gen_var_start")))
        row.addWidget(start_edit)

        stop_edit = QLineEdit("10")
        stop_edit.setMaximumWidth(70)
        row.addWidget(QLabel(get_text("script_gen_var_stop")))
        row.addWidget(stop_edit)

        step_edit = QLineEdit("1")
        step_edit.setMaximumWidth(70)
        row.addWidget(QLabel(get_text("script_gen_var_step")))
        row.addWidget(step_edit)

        values_edit = QLineEdit()
        values_edit.setPlaceholderText(get_text("script_gen_var_values_ph"))
        row.addWidget(values_edit, stretch=1)

        delete_button = QPushButton("×")
        delete_button.setMaximumWidth(30)
        delete_button.clicked.connect(
            lambda: self._remove_variable_row(row_widget)
        )
        row.addWidget(delete_button)

        self._var_container.addWidget(row_widget)
        self._var_rows.append(
            {
                "widget": row_widget,
                "name": name_edit,
                "start": start_edit,
                "stop": stop_edit,
                "step": step_edit,
                "values": values_edit,
            }
        )
        if hasattr(self, "add_variable_button"):
            self.add_variable_button.setEnabled(len(self._var_rows) < 2)

    def _remove_variable_row(self, widget: QWidget) -> None:
        if len(self._var_rows) <= 1:
            return
        self._var_container.removeWidget(widget)
        self._var_rows = [
            row for row in self._var_rows if row["widget"] is not widget
        ]
        widget.deleteLater()
        self.add_variable_button.setEnabled(True)

    def _update_strategy_widgets(self, _index: int = -1) -> None:
        is_custom = (
            hasattr(self, "strategy_combo")
            and self.strategy_combo.currentData() == "custom"
        )
        if hasattr(self, "custom_description_label"):
            self.custom_description_label.setVisible(is_custom)
            self.custom_description_edit.setVisible(is_custom)
            self.custom_supported_label.setVisible(is_custom)

    def _build_result_group(self) -> QGroupBox:
        group = QGroupBox(get_text("script_gen_result_group"))
        form = QFormLayout(group)
        form.setSpacing(8)

        self.port_name_edit = QLineEdit("Port_S_data_1")
        form.addRow(get_text("script_gen_port_name"), self.port_name_edit)
        self.port_traces_edit = QLineEdit("S11 dB")
        self.port_traces_edit.setPlaceholderText(get_text("script_gen_port_traces_ph"))
        form.addRow(get_text("script_gen_port_traces"), self.port_traces_edit)

        observer_container = QWidget()
        observer_row = QHBoxLayout(observer_container)
        observer_row.setContentsMargins(0, 0, 0, 0)
        self.obs_check = QCheckBox(get_text("script_gen_obs_check"))
        self.obs_name_edit = QLineEdit()
        self.obs_name_edit.setPlaceholderText(get_text("script_gen_obs_name_ph"))
        self.obs_name_edit.setEnabled(False)
        self.obs_check.toggled.connect(self.obs_name_edit.setEnabled)
        observer_row.addWidget(self.obs_check)
        observer_row.addWidget(self.obs_name_edit, stretch=1)
        form.addRow(get_text("script_gen_obs_label"), observer_container)

        frequency_container = QWidget()
        frequency_row = QHBoxLayout(frequency_container)
        frequency_row.setContentsMargins(0, 0, 0, 0)
        self.target_freq_spin = QDoubleSpinBox()
        self.target_freq_spin.setDecimals(6)
        self.target_freq_spin.setRange(0.0, 1.0e15)
        self.target_freq_spin.setValue(2.45)
        self.frequency_unit_combo = QComboBox()
        for unit in ("Hz", "kHz", "MHz", "GHz"):
            self.frequency_unit_combo.addItem(unit, unit)
        self.frequency_unit_combo.setCurrentIndex(
            self.frequency_unit_combo.findData("GHz")
        )
        frequency_row.addWidget(self.target_freq_spin, stretch=1)
        frequency_row.addWidget(self.frequency_unit_combo)
        form.addRow(get_text("script_gen_target_freq"), frequency_container)
        self.data_frequency_unit_combo = QComboBox()
        self.data_frequency_unit_combo.addItem(get_text("script_gen_data_unit_auto"), None)
        for unit in ("Hz", "kHz", "MHz", "GHz"):
            self.data_frequency_unit_combo.addItem(unit, unit)
        form.addRow(get_text("script_gen_data_unit"), self.data_frequency_unit_combo)
        return group

    def _build_runtime_group(self) -> QGroupBox:
        group = QGroupBox(get_text("script_gen_ctrl_group"))
        form = QFormLayout(group)
        form.setSpacing(8)

        self.controller_combo = QComboBox()
        self.controller_combo.addItem(get_text("script_gen_ctrl_matlab"), "matlab")
        self.controller_combo.addItem(get_text("script_gen_ctrl_python"), "python")
        form.addRow(get_text("script_gen_controller"), self.controller_combo)

        self.remesh_check = QCheckBox(get_text("script_gen_remesh"))
        self.remesh_check.setChecked(True)
        form.addRow(get_text("script_gen_remesh_label"), self.remesh_check)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 86400)
        self.timeout_spin.setValue(1800)
        self.timeout_spin.setSuffix(" s")
        form.addRow(get_text("script_gen_timeout"), self.timeout_spin)

        self.max_attempts_spin = QSpinBox()
        self.max_attempts_spin.setRange(1, 10)
        self.max_attempts_spin.setValue(3)
        form.addRow(get_text("script_gen_attempts"), self.max_attempts_spin)

        self.resume_check = QCheckBox(get_text("script_gen_resume"))
        self.resume_check.setChecked(True)
        form.addRow(get_text("script_gen_resume_label"), self.resume_check)
        return group

    def _browse_file(self, target: QLineEdit, file_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("script_gen_select_file"), "", file_filter
        )
        if path:
            target.setText(path)

    def _browse_zip_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            get_text("script_gen_select_zip"),
            self.zip_path_edit.text() or "waveda_script_package.zip",
            "ZIP 压缩包 (*.zip)",
        )
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self.zip_path_edit.setText(path)

    @staticmethod
    def _parse_number(text: str, field_name: str) -> float:
        try:
            return float(text.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} {get_text('script_gen_err_number')}") from exc

    def _collect_variables(self) -> tuple[list[dict[str, Any]], list[str]]:
        variables: list[dict[str, Any]] = []
        shapes: list[str] = []
        for index, row in enumerate(self._var_rows, start=1):
            name = row["name"].text().strip()
            values_text = row["values"].text().strip()
            if values_text:
                try:
                    values = [
                        float(item.strip())
                        for item in values_text.split(",")
                        if item.strip()
                    ]
                except ValueError as exc:
                    raise ValueError(
                        get_text("script_gen_err_values").replace("{idx}", str(index))
                    ) from exc
                variables.append({"name": name, "values": values})
                shapes.append("values")
                continue

            variables.append(
                {
                    "name": name,
                    "start": self._parse_number(
                        row["start"].text(),
                        get_text("script_gen_err_start").replace("{idx}", str(index)),
                    ),
                    "stop": self._parse_number(
                        row["stop"].text(),
                        get_text("script_gen_err_stop").replace("{idx}", str(index)),
                    ),
                    "step": self._parse_number(
                        row["step"].text(),
                        get_text("script_gen_err_step").replace("{idx}", str(index)),
                    ),
                }
            )
            shapes.append("range")
        return variables, shapes

    def _normalized_strategy(self, shapes: list[str]) -> str:
        selected = str(self.strategy_combo.currentData())
        if selected != "auto_external":
            return selected
        if shapes and len(set(shapes)) == 1:
            return "explicit_values" if shapes[0] == "values" else "range"
        return "dual_param" if len(shapes) == 2 else "single_param"

    def _zip_destination(self) -> Path:
        raw_path = self.zip_path_edit.text().strip()
        if not raw_path:
            return Path()
        destination = Path(raw_path)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        return destination

    def collect_config(self) -> dict[str, Any]:
        """Build normalized automation config without touching target paths."""

        variables, shapes = self._collect_variables()
        destination = self._zip_destination()
        package_dir = "" if not self.zip_path_edit.text().strip() else str(
            destination.parent
        )

        results: list[dict[str, Any]] = [
            {
                "name": self.port_name_edit.text().strip(),
                "type": "port",
                "traces": [
                    trace.strip()
                    for trace in self.port_traces_edit.text()
                    .replace("，", ",")
                    .split(",")
                    if trace.strip()
                ],
            }
        ]
        if self.obs_check.isChecked():
            results.append(
                {
                    "name": self.obs_name_edit.text().strip(),
                    "type": "obv",
                    "traces": ["value"],
                }
            )

        return build_task_config(
            package_dir=package_dir,
            waveda_exe=self.exe_edit.text().strip(),
            project_file=self.tsp_edit.text().strip(),
            controller=str(self.controller_combo.currentData()),
            sweep_vars=variables,
            strategy=self._normalized_strategy(shapes),
            results=results,
            custom_description=self.custom_description_edit.toPlainText(),
            target_freq=self.target_freq_spin.value(),
            frequency_unit=str(self.frequency_unit_combo.currentData()),
            data_frequency_unit=self.data_frequency_unit_combo.currentData(),
            timeout_seconds=self.timeout_spin.value(),
            max_attempts=self.max_attempts_spin.value(),
            force_remesh=self.remesh_check.isChecked(),
            resume=self.resume_check.isChecked(),
        )

    # Kept as a private alias for callers from the previous dialog version.
    def _collect_config(self) -> dict[str, Any]:
        return self.collect_config()

    def check_configuration(
        self, *, show_message: bool = True
    ) -> list[ValidationIssue]:
        """Run generation-time semantic checks only; never probe target paths."""

        try:
            config = self.collect_config()
            issues = validate_generation_config(config)
            if not issues:
                ScriptPackage(config).generate_files()
        except (ValueError, PackageBuildError) as exc:
            issues = [
                ValidationIssue(
                    code="package_generation_failed",
                    field="dialog",
                    message=str(exc),
                )
            ]

        if show_message:
            if issues:
                details = "\n".join(f"• {issue.message}" for issue in issues)
                QMessageBox.warning(self, "配置检查未通过", details)
            else:
                QMessageBox.information(
                    self,
                    "配置检查通过",
                    "本地配置格式有效。\n"
                    "异地 WavEDA.exe 和 .tsp 是否存在，将在异地运行 check 时检查。",
                )
        return issues

    def _check_clicked(self) -> None:
        self.check_configuration(show_message=True)

    def preview_text(self) -> str:
        config = self.collect_config()
        files = ScriptPackage(config).generate_files()
        destination = self._zip_destination()
        lines = [
            f"本地 ZIP 保存位置：{destination}",
            f"压缩包内共 {len(files)} 个文件：",
            "",
        ]
        lines.extend(f"  • {name}" for name in files)
        lines.extend(
            [
                "",
                "外部文件：不会包含外部 .tsp 工程文件。",
                f"异地 WavEDA.exe：{config['target']['waveda_exe']}",
                f"异地 .tsp：{config['target']['project_file']}",
                "",
                "运行方式：直接运行主控制器，自动执行 "
                "check → smoke → endpoint → run。",
            ]
        )
        return "\n".join(lines)

    def _preview(self) -> None:
        try:
            preview = self.preview_text()
        except (ValueError, PackageBuildError) as exc:
            QMessageBox.warning(self, "无法预览", str(exc))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("压缩包清单预览")
        dialog.setMinimumSize(560, 380)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(preview)
        layout.addWidget(text)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def generate_package(self) -> Path:
        """Validate and write the selected controller package as a ZIP."""

        config = self.collect_config()
        issues = validate_generation_config(config)
        if issues:
            details = "；".join(issue.message for issue in issues)
            raise PackageBuildError(f"任务配置无效：{details}")
        return ScriptPackage(config).write_zip(self._zip_destination())

    def _generate(self) -> None:
        try:
            written = self.generate_package()
            files = ScriptPackage(self.collect_config()).generate_files()
        except (ValueError, OSError, PackageBuildError) as exc:
            QMessageBox.critical(self, "生成失败", str(exc))
            return

        manifest = "\n".join(f"  ✓ {name}" for name in files)
        QMessageBox.information(
            self,
            "生成完成",
            f"压缩包已保存到：\n{written}\n\n"
            f"包内文件：\n{manifest}\n\n"
            "复制到异地电脑并解压后，直接运行主控制器即可。",
        )
