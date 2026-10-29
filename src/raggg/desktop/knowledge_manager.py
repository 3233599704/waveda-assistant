"""
知识库管理界面 — 查看/编辑知识结构、导入PDF/PPT并AI辅助分类
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from raggg.config import Settings
from raggg.desktop.source_viewer import SourceViewer
from raggg.i18n import get_text
from raggg.knowledge_package import current_knowledge_version, export_knowledge_package
from raggg.pipeline.knowledge_import import (
    analyze_document,
    build_import_markdown,
    extract_pptx_text,
    list_all_subdirs,
    suggest_subdir,
)
from raggg.theme import get_colors

COLORS = get_colors()


class KnowledgeManager(QWidget):
    knowledge_changed = Signal()
    _CATEGORY_DEFAULT_PRIORITY = {
        "01_team_tutorials": 5,
        "02_software_manual": 4,
        "03_examples": 4,
        "04_error_cases": 3,
        "05_reference": 2,
        "06_theory_notes": 1,
        "07_scripting_automation_all": 5,
    }
    _INVALID_FOLDER_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
    _WINDOWS_RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if not settings.can_manage_knowledge:
            raise PermissionError("用户版无权打开知识库维护功能。")
        self.settings = settings
        self._kb_root = settings.obsidian_vault_root
        self._pending_import_path: str = ""
        self._pending_import_type: str = ""
        self._items_by_path: dict[str, QTreeWidgetItem] = {}
        self._build_ui()
        self._load_tree(select_path=self._last_imported_output())

    # ─── UI ─────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        desc = QLabel(get_text("kbm_desc"))
        desc.setStyleSheet(f"color:{COLORS['subtle']};font-size:12px;margin-bottom:4px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 搜索栏
        search_bar = QHBoxLayout()
        search_bar.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索文件...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search)
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background: {COLORS['surface3']}; color: {COLORS['text']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 8px 14px; "
            f"font-size: 13px; }}"
            f"QLineEdit:focus {{ border-color: {COLORS['accent']}; }}"
        )
        search_bar.addWidget(self.search_edit)
        layout.addLayout(search_bar)

        # 提示：双击打开文件
        hint = QLabel("双击文件或目录在新窗口中查看和编辑")
        hint.setStyleSheet(f"color:{COLORS['subtle']};font-size:11px;")
        layout.addWidget(hint)

        # 树（独占整行）
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setAnimated(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background: {COLORS['surface2']}; "
            f"color: {COLORS['text']}; "
            f"border: 1.5px solid {COLORS['subtle']}; border-radius: 8px; "
            f"font-size: 13px; outline: none; }}"
            f"QTreeWidget::item {{ padding: 5px 10px; border-radius: 4px; margin: 2px 0; }}"
            f"QTreeWidget::item:hover {{ background: {COLORS['surface']}; }}"
            f"QTreeWidget::item:selected {{ background: {COLORS['accent']}; color: #fff; }}"
            f"QTreeWidget::branch:has-children:!has-siblings:closed {{"
            f"  image: none; border: none; }}"
            f"QTreeWidget::branch:has-children:!has-siblings:open {{"
            f"  image: none; border: none; }}"
        )
        layout.addWidget(self.tree, stretch=1)

        # ── 导入区 ──
        import_section = QWidget()
        import_layout = QVBoxLayout(import_section)
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.setSpacing(6)

        import_label = QLabel(get_text("kbm_import_title"))
        import_label.setStyleSheet(f"color:{COLORS['text']};font-weight:700;")
        import_layout.addWidget(import_label)

        # Row 1: 选择文件
        row1 = QHBoxLayout(); row1.setSpacing(8)
        self.file_select_btn = QPushButton(get_text("kbm_select_file"))
        self.file_select_btn.clicked.connect(self._select_file)
        row1.addWidget(self.file_select_btn)
        self.file_status = QLabel(get_text("kbm_no_file"))
        self.file_status.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        row1.addWidget(self.file_status, stretch=1)
        import_layout.addLayout(row1)

        # Row 2: 分类 + 子目录 + 重要度
        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(QLabel(get_text("kbm_import_target") + ":"))
        self.category_combo = QComboBox()
        self._populate_categories()
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        row2.addWidget(self.category_combo)

        row2.addWidget(QLabel(get_text("kbm_import_subdir") + ":"))
        self.subdir_btn = QPushButton(get_text("kbm_subdir_auto"))
        self.subdir_btn.clicked.connect(self._popup_subdir_menu)
        self._subdir_value = "__AUTO__"
        row2.addWidget(self.subdir_btn)

        row2.addWidget(QLabel(get_text("kbm_priority_label") + ":"))
        self.priority_combo = QComboBox()
        for i in range(1, 6):
            self.priority_combo.addItem(get_text(f"kbm_priority_{i}"), i)
        self._sync_priority_for_category()
        row2.addWidget(self.priority_combo)
        import_layout.addLayout(row2)

        target_row = QHBoxLayout(); target_row.setSpacing(8)
        self.target_path_label = QLabel()
        self.target_path_label.setWordWrap(True)
        self.target_path_label.setStyleSheet(
            f"color:{COLORS['muted']};font-size:11px;"
        )
        target_row.addWidget(self.target_path_label, stretch=1)
        self.new_node_btn = QPushButton(get_text("kbm_new_node"))
        self.new_node_btn.clicked.connect(self._new_target_node)
        target_row.addWidget(self.new_node_btn)
        self.new_subdir_btn = QPushButton(get_text("kbm_new_subdir"))
        self.new_subdir_btn.clicked.connect(self._new_subdir)
        target_row.addWidget(self.new_subdir_btn)
        import_layout.addLayout(target_row)
        self._refresh_target_path_label()

        # Row 3: 备注 + 确认导入
        row3 = QHBoxLayout(); row3.setSpacing(8)
        row3.addWidget(QLabel(get_text("kbm_import_desc_label") + " *:"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText(get_text("kbm_import_desc_placeholder"))
        row3.addWidget(self.desc_edit, stretch=1)

        self.confirm_btn = QPushButton(get_text("kbm_confirm_import_btn"))
        self.confirm_btn.clicked.connect(self._confirm_import)
        row3.addWidget(self.confirm_btn)
        import_layout.addLayout(row3)

        layout.addWidget(import_section)

        release_row = QHBoxLayout()
        release_hint = QLabel("完成内容审核和索引重建后，可导出供用户版安装的知识库更新包。")
        release_hint.setWordWrap(True)
        release_hint.setStyleSheet(f"color:{COLORS['subtle']};font-size:11px;")
        release_row.addWidget(release_hint, stretch=1)
        self.export_package_btn = QPushButton("导出知识库更新包")
        self.export_package_btn.clicked.connect(self._export_knowledge_package)
        release_row.addWidget(self.export_package_btn)
        layout.addLayout(release_row)

    def _export_knowledge_package(self) -> None:
        default_version = current_knowledge_version(self.settings)
        version, accepted = QInputDialog.getText(
            self,
            "导出知识库更新包",
            "知识库版本号：",
            text=default_version,
        )
        if not accepted or not version.strip():
            return
        suggested = self.settings.project_root / f"WavEDA_Knowledge_{version.strip()}.wkb"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "保存知识库更新包",
            str(suggested),
            "WavEDA 知识库更新包 (*.wkb)",
        )
        if not target:
            return
        try:
            info = export_knowledge_package(
                self.settings,
                Path(target),
                version,
            )
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self,
            "导出完成",
            f"知识库版本：{info.version}\n文件数量：{info.file_count}\n\n{Path(target).with_suffix('.wkb')}",
        )

    # ─── Tree ──────────────────────────────────
    _CAT_I18N = {
        "01_team_tutorials": "kbm_cat_01", "02_software_manual": "kbm_cat_02",
        "03_examples": "kbm_cat_03", "04_error_cases": "kbm_cat_04",
        "05_reference": "kbm_cat_05", "06_theory_notes": "kbm_cat_06",
        "07_scripting_automation_all": "kbm_cat_07",
        "tutorials": "kbm_sub_tutorials", "Circuit": "kbm_example_circuit",
        "EM": "kbm_example_em", "Mech": "kbm_example_mech",
        "Multi-Physics": "kbm_example_multi", "Thermal": "kbm_example_thermal",
    }

    def _load_tree(self, select_path: Path | None = None) -> None:
        self.tree.clear()
        self._items_by_path.clear()
        if self._kb_root.exists():
            self._add_tree_items(self.tree.invisibleRootItem(), self._kb_root)
        if select_path is not None:
            self._select_tree_path(select_path)

    def _add_tree_items(self, parent: QTreeWidgetItem, path: Path) -> None:
        # 目录在前，文件在后
        entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                display_name = get_text(self._CAT_I18N.get(entry.name, "")) or entry.name
                md_count = sum(1 for _ in entry.rglob("*.md"))
                item = QTreeWidgetItem(parent, [f"📁 {display_name}"])
                item.setData(0, Qt.UserRole, str(entry))
                self._items_by_path[str(entry.resolve())] = item
                item.setToolTip(0, f"{md_count} 个文档")
                # 文件夹用粗体区分
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
                self._add_tree_items(item, entry)
            elif entry.suffix == ".md":
                item = QTreeWidgetItem(parent, [f"📄 {entry.stem}"])
                item.setData(0, Qt.UserRole, str(entry))
                self._items_by_path[str(entry.resolve())] = item
                item.setToolTip(0, str(entry))
        if parent == self.tree.invisibleRootItem():
            pass  # 默认全部折叠，用户自行展开

    def _select_tree_path(self, path: Path) -> None:
        item = self._items_by_path.get(str(path.resolve()))
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def _on_tree_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        filepath = item.data(0, Qt.UserRole)
        if not filepath:
            return
        path = Path(filepath)
        if path.is_file() and path.suffix == ".md":
            self._open_source_viewer(path)

    def _open_source_viewer(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            from raggg.desktop.rendering import markdown_to_html, web_wrapper
            html_body = markdown_to_html(text)
            html_content = web_wrapper(html_body)
        except Exception:
            import html as _html
            html_content = f"<pre>{_html.escape(text)}</pre>"
        viewer = SourceViewer(path.stem, html_content, self, file_path=path)
        viewer.knowledge_changed.connect(self.knowledge_changed.emit)
        viewer.show()

    def _on_search(self, text: str) -> None:
        """过滤树中匹配文件名的条目"""
        for i in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(i), text.lower())

    def _filter_item(self, item: QTreeWidgetItem, text: str) -> bool:
        visible = False
        filepath = item.data(0, Qt.UserRole)
        name = item.text(0).lower()
        if filepath:
            path = Path(filepath)
            if path.is_file():
                visible = text in name or text in str(path).lower()
            else:
                # 目录：递归检查子项
                child_visible = False
                for i in range(item.childCount()):
                    if self._filter_item(item.child(i), text):
                        child_visible = True
                visible = child_visible or (text in name)
        item.setHidden(not visible)
        if visible and not text:
            item.setExpanded(True)
        return visible

    # ─── 右键菜单：删除文件 ─────────────────────
    def _on_tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        filepath = item.data(0, Qt.UserRole)
        if not filepath:
            return
        path = Path(filepath)
        menu = QMenu(self)
        if path.is_dir():
            use_action = QAction(get_text("kbm_use_as_target"), self)
            use_action.triggered.connect(lambda: self._set_target_from_directory(path))
            menu.addAction(use_action)
            new_action = QAction(get_text("kbm_new_subdir"), self)
            new_action.triggered.connect(lambda: self._new_subdir(path))
            menu.addAction(new_action)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return

        del_action = QAction(get_text("kbm_delete_file"), self)
        del_action.triggered.connect(lambda: self._delete_file(path, item))
        menu.addAction(del_action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _delete_file(self, path: Path, item: QTreeWidgetItem) -> None:
        name = path.name
        reply = QMessageBox.question(
            self,
            get_text("kbm_delete_confirm_title"),
            get_text("kbm_delete_confirm_msg").replace("{name}", name),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            path.unlink()
            parent = item.parent() or self.tree.invisibleRootItem()
            parent.removeChild(item)
            # 移除空目录
            parent_path = Path(path.parent)
            if parent_path != self._kb_root and not any(parent_path.iterdir()):
                parent_path.rmdir()
                self._load_tree()
            self.knowledge_changed.emit()
        except Exception as e:
            QMessageBox.warning(self, get_text("kbm_delete_error"), str(e))

    # ─── Import ────────────────────────────────
    def _populate_categories(self) -> None:
        standard = [
            ("01_team_tutorials", get_text("kbm_cat_01")),
            ("02_software_manual", get_text("kbm_cat_02")),
            ("03_examples", get_text("kbm_cat_03")),
            ("04_error_cases", get_text("kbm_cat_04")),
            ("05_reference", get_text("kbm_cat_05")),
            ("06_theory_notes", get_text("kbm_cat_06")),
            ("07_scripting_automation_all", get_text("kbm_cat_07")),
        ]
        labels = dict(standard)
        actual = []
        if self._kb_root.exists():
            actual = [
                path.name
                for path in sorted(
                    self._kb_root.iterdir(), key=lambda path: path.name.lower()
                )
                if path.is_dir() and not path.name.startswith(".")
            ]
        category_ids = [category_id for category_id, _label in standard]
        category_ids.extend(
            category_id for category_id in actual if category_id not in labels
        )
        current = self.category_combo.currentData() if self.category_combo.count() else None
        self.category_combo.clear()
        for category_id in category_ids:
            self.category_combo.addItem(labels.get(category_id, category_id), category_id)
        if current:
            index = self.category_combo.findData(current)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)

    def _on_category_changed(self, _index: int) -> None:
        self._subdir_value = "__AUTO__"
        self.subdir_btn.setText(get_text("kbm_subdir_auto"))
        if hasattr(self, "priority_combo"):
            self._sync_priority_for_category()
        if hasattr(self, "target_path_label"):
            self._refresh_target_path_label()

    def _sync_priority_for_category(self) -> None:
        priority = self._CATEGORY_DEFAULT_PRIORITY.get(self.category_combo.currentData(), 3)
        index = self.priority_combo.findData(priority)
        if index >= 0:
            self.priority_combo.setCurrentIndex(index)

    def _popup_subdir_menu(self) -> None:
        """弹出级联子目录菜单，鼠标悬停自动展开子级"""
        cat_id = self.category_combo.currentData()
        cat_path = self._kb_root / cat_id
        menu = QMenu(self)

        # 首选项
        auto_action = menu.addAction(get_text("kbm_subdir_auto"))
        auto_action.triggered.connect(lambda: self._set_subdir("__AUTO__", get_text("kbm_subdir_auto")))
        menu.addAction(get_text("kbm_subdir_root")).triggered.connect(
            lambda: self._set_subdir("", get_text("kbm_subdir_root")))
        menu.addSeparator()

        if cat_path.exists():
            self._build_subdir_menu(menu, cat_path, "")

        menu.exec(self.subdir_btn.mapToGlobal(self.subdir_btn.rect().bottomLeft()))

    def _build_subdir_menu(self, parent_menu: QMenu, base: Path, prefix: str) -> None:
        """递归构建级联菜单，深层目录作为子菜单悬停展开"""
        for entry in sorted(base.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            display = self._CAT_I18N.get(entry.name, entry.name)
            rel_path = (prefix + "/" + entry.name).lstrip("/")
            subdirs = [d for d in entry.iterdir() if d.is_dir() and not d.name.startswith(".")]

            if subdirs:
                submenu = QMenu(display, parent_menu)
                parent_menu.addMenu(submenu)
                # 子菜单里也加一个"选此目录"的选项
                pick_action = submenu.addAction(f"[{display}]")
                pick_action.triggered.connect(lambda checked=False, rp=rel_path, d=display: self._set_subdir(rp, d))
                submenu.addSeparator()
                self._build_subdir_menu(submenu, entry, rel_path)
            else:
                action = parent_menu.addAction(display)
                action.triggered.connect(lambda checked=False, rp=rel_path, d=display: self._set_subdir(rp, d))

    def _set_subdir(self, value: str, display: str) -> None:
        self._subdir_value = value
        self.subdir_btn.setText(display)
        self._refresh_target_path_label()

    def _refresh_target_path_label(self) -> None:
        category = self.category_combo.currentData()
        if not category:
            self.target_path_label.setText(get_text("kbm_target_path_empty"))
            return
        subdir = self._subdir_value
        if subdir == "__AUTO__":
            path_text = (
                f"knowledge_base/{category}/"
                f"{get_text('kbm_target_path_auto')}"
            )
        elif subdir:
            path_text = f"knowledge_base/{category}/{subdir}"
        else:
            path_text = f"knowledge_base/{category}"
        self.target_path_label.setText(
            f"{get_text('kbm_target_path_label')}: {path_text}"
        )

    def _set_target_from_directory(self, directory: Path) -> None:
        try:
            relative = directory.resolve().relative_to(self._kb_root.resolve())
        except ValueError:
            QMessageBox.warning(
                self, get_text("kbm_invalid_path"), get_text("kbm_path_outside_root")
            )
            return
        if not relative.parts:
            return
        category = relative.parts[0]
        index = self.category_combo.findData(category)
        if index < 0:
            self.category_combo.addItem(category, category)
            index = self.category_combo.findData(category)
        self.category_combo.setCurrentIndex(index)
        subdir = "/".join(relative.parts[1:])
        self._set_subdir(subdir, subdir or get_text("kbm_subdir_root"))

    def _new_target_node(self) -> None:
        name, accepted = QInputDialog.getText(
            self, get_text("kbm_new_node"), get_text("kbm_new_node_prompt")
        )
        if not accepted:
            return
        parts = self._validated_relative_parts(name, allow_nested=False)
        if parts is None:
            return
        directory = self._kb_root / parts[0]
        if directory.exists():
            QMessageBox.information(
                self, get_text("kbm_folder_exists"), get_text("kbm_folder_exists_msg")
            )
        else:
            directory.mkdir(parents=True, exist_ok=False)
        self._populate_categories()
        self._load_tree(select_path=directory)
        self._set_target_from_directory(directory)

    def _new_subdir(self, parent_directory: Path | None = None) -> None:
        category = self.category_combo.currentData()
        if not category:
            return
        if parent_directory is None:
            base = self._kb_root / category
            if self._subdir_value not in {"", "__AUTO__"}:
                base = base / self._subdir_value
        else:
            base = parent_directory
        try:
            display_parent = base.resolve().relative_to(
                self._kb_root.resolve()
            ).as_posix()
        except ValueError:
            QMessageBox.warning(
                self, get_text("kbm_invalid_path"), get_text("kbm_path_outside_root")
            )
            return
        name, accepted = QInputDialog.getText(
            self,
            get_text("kbm_new_subdir"),
            get_text("kbm_new_subdir_prompt").replace("{parent}", display_parent),
        )
        if not accepted:
            return
        parts = self._validated_relative_parts(name, allow_nested=True)
        if parts is None:
            return
        directory = base.joinpath(*parts)
        try:
            directory.resolve().relative_to(self._kb_root.resolve())
        except ValueError:
            QMessageBox.warning(
                self, get_text("kbm_invalid_path"), get_text("kbm_path_outside_root")
            )
            return
        if directory.exists():
            QMessageBox.information(
                self, get_text("kbm_folder_exists"), get_text("kbm_folder_exists_msg")
            )
        else:
            directory.mkdir(parents=True, exist_ok=False)
        self._load_tree(select_path=directory)
        self._set_target_from_directory(directory)

    def _validated_relative_parts(
        self, value: str, *, allow_nested: bool
    ) -> tuple[str, ...] | None:
        raw_value = value.strip()
        is_absolute = bool(
            raw_value.startswith(("/", "\\"))
            or re.match(r"^[A-Za-z]:", raw_value)
        )
        normalized = raw_value.replace("\\", "/").strip("/")
        parts = tuple(part.strip() for part in normalized.split("/") if part.strip())
        invalid = (
            is_absolute
            or not parts
            or (not allow_nested and len(parts) != 1)
            or any(part in {".", ".."} for part in parts)
            or any(self._INVALID_FOLDER_CHARS.search(part) for part in parts)
            or any(part.endswith((" ", ".")) for part in parts)
            or any(part.upper() in self._WINDOWS_RESERVED_NAMES for part in parts)
            or any(part.startswith(".") for part in parts)
        )
        if invalid:
            QMessageBox.warning(
                self, get_text("kbm_invalid_path"), get_text("kbm_invalid_path_msg")
            )
            return None
        return parts

    # ── 文件选择 ────────────────────────────────
    def _select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, get_text("kbm_select_file_title"), "",
            "Documents (*.pdf *.pptx *.docx *.md)"
        )
        if not path:
            return
        suffix = path.lower()
        if suffix.endswith(".pdf"):
            self._pending_import_type = "pdf"
        elif suffix.endswith(".pptx"):
            self._pending_import_type = "pptx"
        elif suffix.endswith(".docx"):
            self._pending_import_type = "docx"
        else:
            self._pending_import_type = "md"
        self._pending_import_path = path
        self.file_status.setText(f"📎 {Path(path).name}")
        self.file_status.setStyleSheet(f"color:{COLORS['accent']};font-size:11px;")

    # ── 确认导入（强制备注） ─────────────────────
    def _confirm_import(self) -> None:
        if not self._pending_import_path:
            QMessageBox.information(self, get_text("kbm_no_file"), get_text("kbm_no_file_msg"))
            return
        user_desc = self.desc_edit.text().strip()
        if not user_desc:
            QMessageBox.information(self, get_text("kbm_notes_required"), get_text("kbm_notes_required_msg"))
            return
        imported_path = self._import_file(
            self._pending_import_path, self._pending_import_type
        )
        if imported_path is None:
            return
        self._pending_import_path = ""
        self._pending_import_type = ""
        self.file_status.setText(get_text("kbm_no_file"))
        self.file_status.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")

    def _import_file(self, filepath: str, filetype: str) -> Path | None:
        filepath = Path(filepath)

        # 1. 提取文本
        if filetype == "md":
            text = filepath.read_text(encoding="utf-8", errors="ignore")
            # 去掉 YAML front matter
            if text.startswith("---"):
                end = text.find("---", 3)
                if end > 0:
                    text = text[end + 3:].strip()
        elif filetype == "docx":
            try:
                from raggg.pipeline.ingestion import _extract_docx_text
                text = _extract_docx_text(filepath)
            except ImportError:
                text = f"[DOCX: {filepath.name}]\n\n(需要安装 python-docx)"
        elif filetype == "pdf":
            try:
                from raggg.pipeline.ingestion import _extract_pdf_text
                text = _extract_pdf_text(filepath)
            except ImportError:
                text = f"[PDF: {filepath.name}]\n\n(需要安装 pypdf)"
        else:
            text = extract_pptx_text(filepath)

        if not text.strip():
            QMessageBox.warning(self, get_text("kbm_import_failed"), get_text("kbm_import_empty"))
            return None

        # 2. 确定目标路径（大分类 + AI/手动子目录，支持多级深度）
        cat_id = self.category_combo.currentData()
        if not cat_id:
            QMessageBox.warning(
                self, get_text("kbm_invalid_path"), get_text("kbm_target_path_empty")
            )
            return None
        priority = int(self.priority_combo.currentData())
        base_dir = self._kb_root / cat_id
        user_desc = self.desc_edit.text().strip()
        subdir_choice = self._subdir_value

        if subdir_choice == "__AUTO__":
            all_subdirs = list_all_subdirs(base_dir)
            chosen_subdir = suggest_subdir(
                self.settings, text, filepath.stem, user_desc, all_subdirs
            )
            target_dir = base_dir / chosen_subdir if chosen_subdir else base_dir
        elif subdir_choice:
            target_dir = base_dir / subdir_choice
        else:
            target_dir = base_dir

        try:
            target_dir.resolve().relative_to(self._kb_root.resolve())
        except ValueError:
            QMessageBox.warning(
                self, get_text("kbm_invalid_path"), get_text("kbm_path_outside_root")
            )
            return None

        safe_name = re.sub(r"[^\w\-.]", "_", filepath.stem).strip(" ._")
        safe_name = safe_name or "imported_document"
        out_path = self._unique_path(target_dir, safe_name, ".md")
        archive_dir = (
            self._kb_root / ".source_files" / datetime.now().strftime("%Y-%m-%d")
        )
        archive_path = self._unique_path(
            archive_dir, safe_name, filepath.suffix.lower() or ".source"
        )
        archive_relative = archive_path.relative_to(self._kb_root).as_posix()

        # 3. 生成 Markdown，记录可追溯的原文件归档位置
        markdown = build_import_markdown(
            filepath,
            text,
            cat_id,
            priority,
            source_archive=archive_relative,
        )

        # 4. AI 分析
        suggestion = analyze_document(self.settings, text, filepath.stem, user_desc)

        # 5. 预览并确认
        preview = (
            f"{get_text('kbm_preview_file')}: {filepath.name}\n"
            f"{get_text('kbm_preview_target')}: "
            f"{out_path.relative_to(self._kb_root.parent)}\n"
            f"{get_text('kbm_source_archive')}: {archive_relative}\n"
            f"{get_text('kbm_preview_suggestion')}:\n{suggestion}\n\n"
            f"---\n{markdown[:500]}...\n"
        )
        reply = QMessageBox.question(
            self, get_text("kbm_confirm_import"), preview,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return None

        # 6. 归档原文件并原子写入转换后的 Markdown
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filepath, archive_path)
            target_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = out_path.with_name(f".{out_path.name}.importing")
            temporary_path.write_text(markdown, encoding="utf-8")
            temporary_path.replace(out_path)
            self._append_import_manifest(
                source_path=filepath,
                archive_path=archive_path,
                output_path=out_path,
                category=cat_id,
                priority=priority,
                description=user_desc,
            )
        except OSError as exc:
            QMessageBox.warning(self, get_text("kbm_import_failed"), str(exc))
            return None

        self.search_edit.clear()
        self._load_tree(select_path=out_path)
        self.desc_edit.clear()
        self.knowledge_changed.emit()

        # 7. 主窗口收到信号后在后台增量更新索引
        msg = (
            f"{get_text('kbm_import_ok_msg')}: "
            f"{out_path.relative_to(self._kb_root.parent)}\n"
            f"{get_text('kbm_source_archive')}: {archive_relative}\n"
            f"{get_text('kbm_index_update_queued')}"
        )
        QMessageBox.information(self, get_text("kbm_import_done"), msg)
        return out_path

    @staticmethod
    def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
        candidate = directory / f"{stem}{suffix}"
        index = 2
        while candidate.exists():
            candidate = directory / f"{stem}_{index}{suffix}"
            index += 1
        return candidate

    def _append_import_manifest(
        self,
        *,
        source_path: Path,
        archive_path: Path,
        output_path: Path,
        category: str,
        priority: int,
        description: str,
    ) -> None:
        manifest_dir = self._kb_root / ".imports"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "manifest.json"
        records: list[dict[str, object]] = []
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    records = [item for item in loaded if isinstance(item, dict)]
            except (OSError, ValueError, TypeError):
                records = []
        records.append(
            {
                "imported_at": datetime.now().isoformat(timespec="seconds"),
                "source_name": source_path.name,
                "source_archive": archive_path.relative_to(self._kb_root).as_posix(),
                "output_path": output_path.relative_to(self._kb_root).as_posix(),
                "category": category,
                "priority": priority,
                "description": description,
                "index_status": "queued",
            }
        )
        temporary_path = manifest_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(manifest_path)

    def _last_imported_output(self) -> Path | None:
        manifest_path = self._kb_root / ".imports" / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            records = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                return None
            for record in reversed(records):
                if not isinstance(record, dict):
                    continue
                relative = record.get("output_path")
                if not isinstance(relative, str) or not relative:
                    continue
                candidate = (self._kb_root / relative).resolve()
                candidate.relative_to(self._kb_root.resolve())
                if candidate.is_file():
                    return candidate
        except (OSError, ValueError, TypeError):
            return None
        return None
