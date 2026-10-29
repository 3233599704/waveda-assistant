"""
纠错审查系统 — 多轮纠错 + 审核队列 + 知识库写入
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from raggg.i18n import get_text
from raggg.theme import get_colors

COLORS = get_colors()

_PENDING_CORRECTIONS_PATH: Path | None = None


def _pending_file(project_root: Path) -> Path:
    path = project_root / "data" / "corrections_pending.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _history_file(project_root: Path) -> Path:
    path = project_root / "data" / "corrections_history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_json(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pending(project_root: Path) -> list[dict]:
    return _load_json(_pending_file(project_root))


def save_pending(project_root: Path, items: list[dict]) -> None:
    _save_json(_pending_file(project_root), items)


def load_history(project_root: Path) -> list[dict]:
    return _load_json(_history_file(project_root))


def save_history(project_root: Path, items: list[dict]) -> None:
    _save_json(_history_file(project_root), items)


def add_to_history(project_root: Path, item: dict) -> None:
    items = load_history(project_root)
    items.insert(0, item)
    save_history(project_root, items)


def update_history_item(project_root: Path, index: int, item: dict) -> None:
    items = load_history(project_root)
    if 0 <= index < len(items):
        items[index] = item
        save_history(project_root, items)


def delete_history_item(project_root: Path, index: int) -> None:
    items = load_history(project_root)
    if 0 <= index < len(items):
        del items[index]
        save_history(project_root, items)


def _write_approved_entry(project_root: Path, item: dict, content: str) -> Path:
    faq_path = project_root / "knowledge_base" / "01_team_tutorials" / "02_常见问题FAQ.md"
    faq_path.parent.mkdir(parents=True, exist_ok=True)
    correction_id = str(item.get("correction_id", "")).strip() or uuid4().hex
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    start_marker = f"<!-- correction:{correction_id}:start -->"
    end_marker = f"<!-- correction:{correction_id}:end -->"
    entry = (
        f"\n\n{start_marker}\n"
        f"## {item.get('question', 'FAQ')[:60]}\n\n{content}\n\n"
        f"> 审核通过于 {timestamp}\n{end_marker}"
    )
    with faq_path.open("a", encoding="utf-8") as output:
        output.write(entry)
    item["correction_id"] = correction_id
    item["knowledge_path"] = faq_path.relative_to(project_root).as_posix()
    return faq_path


def _remove_approved_entry(project_root: Path, item: dict) -> bool:
    correction_id = str(item.get("correction_id", "")).strip()
    relative_path = str(item.get("knowledge_path", "")).strip()
    if not correction_id or not relative_path:
        return False

    knowledge_root = (project_root / "knowledge_base").resolve()
    target = (project_root / relative_path).resolve()
    try:
        target.relative_to(knowledge_root)
    except ValueError:
        return False
    if not target.is_file():
        return False

    text = target.read_text(encoding="utf-8")
    start_marker = f"<!-- correction:{correction_id}:start -->"
    end_marker = f"<!-- correction:{correction_id}:end -->"
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        return False
    end += len(end_marker)
    updated = text[:start].rstrip() + text[end:]
    target.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return True


# ── 多轮纠错弹窗 ────────────────────────────────────

class CorrectionDialog(QDialog):
    """多轮纠错：AI 润色 → 预览 → 再纠错 → 直到满意 → 提交审核"""

    def __init__(
        self,
        question: str,
        original_answer: str,
        llm_client,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._question = question
        self._original_answer = original_answer
        self._client = llm_client
        self._correction_history: list[str] = []  # 用户修正意见历史
        self._refined_text = ""
        self._round = 0

        self.setWindowTitle("纠错 — 多轮修正")
        self.resize(680, 600)
        self.setMinimumSize(520, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 原问题
        q_group = QGroupBox("原问题")
        q_layout = QVBoxLayout(q_group)
        q_label = QLabel(question)
        q_label.setWordWrap(True)
        q_label.setStyleSheet(f"color:{COLORS['text']};")
        q_layout.addWidget(q_label)
        layout.addWidget(q_group)

        # AI 润色结果（只读预览）
        preview_group = QGroupBox("AI 修改结果")
        preview_layout = QVBoxLayout(preview_group)
        self._preview_edit = QTextEdit()
        self._preview_edit.setReadOnly(True)
        self._preview_edit.setStyleSheet(
            f"QTextEdit {{ background:{COLORS['surface3']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; padding:10px; }}"
        )
        self._preview_edit.setPlaceholderText("输入修正意见后，AI 将在本轮润色...")
        preview_layout.addWidget(self._preview_edit)
        layout.addWidget(preview_group, stretch=2)

        # 修正意见输入
        fix_group = QGroupBox("本轮修正意见")
        fix_layout = QVBoxLayout(fix_group)
        self._fix_edit = QTextEdit()
        self._fix_edit.setMaximumHeight(100)
        self._fix_edit.setPlaceholderText("描述哪里不对、该怎么改...")
        self._fix_edit.setStyleSheet(
            f"QTextEdit {{ background:{COLORS['input']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; padding:8px; }}"
        )
        fix_layout.addWidget(self._fix_edit)
        layout.addWidget(fix_group)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._refine_btn = QPushButton("🔄 AI 润色修改")
        self._refine_btn.setCursor(Qt.PointingHandCursor)
        self._refine_btn.clicked.connect(self._do_refine)
        self._refine_btn.setStyleSheet(
            f"QPushButton {{ background:{COLORS['accent']}; color:#fff; "
            f"border:none; border-radius:6px; padding:8px 18px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{COLORS['accent2']}; }}"
        )
        btn_layout.addWidget(self._refine_btn)

        self._submit_btn = QPushButton("✓ 提交审核")
        self._submit_btn.setCursor(Qt.PointingHandCursor)
        self._submit_btn.clicked.connect(self._do_submit)
        self._submit_btn.setEnabled(False)
        self._submit_btn.setStyleSheet(
            f"QPushButton {{ background:{COLORS['surface2']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; padding:8px 18px; }}"
            f"QPushButton:enabled {{ background:{COLORS['accent']}; color:#fff; "
            f"border:none; font-weight:600; }}"
            f"QPushButton:enabled:hover {{ background:{COLORS['accent2']}; }}"
        )
        btn_layout.addWidget(self._submit_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        # 状态
        self._status_label = QLabel("在下方输入修正意见，点击「AI 润色修改」开始。")
        self._status_label.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        layout.addWidget(self._status_label)

    def _do_refine(self) -> None:
        user_fix = self._fix_edit.toPlainText().strip()
        if not user_fix:
            QMessageBox.information(self, "提示", "请先输入修正意见。")
            return
        if self._client is None:
            QMessageBox.warning(self, "无法润色", "当前没有可用的 API 配置，请先在设置中检查 API。")
            return

        round_number = self._round + 1
        correction_history = [*self._correction_history, user_fix]
        self._status_label.setText(f"AI 正在润色（第 {round_number} 轮）...")
        self._refine_btn.setEnabled(False)
        self._status_label.repaint()

        try:
            history_text = "\n".join(
                f"- 第{i+1}轮修正意见：{h}"
                for i, h in enumerate(correction_history)
            )
            prompt = (
                f"原始问题：{self._question}\n\n"
                f"原始回答：{self._original_answer[:2000]}\n\n"
                f"多轮修正历史：\n{history_text}\n\n"
                f"请根据以上所有修正意见，润色为一组准确流畅的FAQ，只输出：\n"
                f"Q: <问题>\nA: <回答>"
            )
            refined = self._client.complete(prompt).strip()
        except Exception as e:
            self._refine_btn.setEnabled(True)
            self._status_label.setText("AI 润色失败，请检查 API 后重试。")
            QMessageBox.warning(self, "润色失败", str(e))
            return

        self._round = round_number
        self._correction_history = correction_history
        self._refined_text = refined
        self._preview_edit.setPlainText(refined)
        self._fix_edit.clear()
        self._submit_btn.setEnabled(True)
        self._refine_btn.setEnabled(True)
        self._status_label.setText(
            f"第 {self._round} 轮润色完成。可继续修正或提交审核。"
        )

    def _do_submit(self) -> None:
        if not self._refined_text:
            QMessageBox.information(self, "提示", "请先完成至少一轮 AI 润色。")
            return
        self.accept()

    @property
    def refined_content(self) -> str:
        return self._refined_text

    @property
    def notes(self) -> str:
        return "；".join(self._correction_history)


# ── 审核标签页 ──────────────────────────────────────

class CorrectionReviewTab(QWidget):
    """审核待审纠错，支持编辑/AI润色/通过/拒绝"""

    knowledge_changed = Signal()  # 通过后通知主窗口重建索引

    def __init__(self, project_root: Path, llm_client, parent=None) -> None:
        super().__init__(parent)
        self._project_root = project_root
        self._client = llm_client
        self._items: list[dict] = []
        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        desc = QLabel("审核通过后纠错内容将写入知识库并重建索引。拒绝则直接删除。")
        desc.setStyleSheet(f"color:{COLORS['muted']};font-size:12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_select)
        self._list.setStyleSheet(
            f"QListWidget {{ background:{COLORS['input']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; font-size:12px; }}"
            f"QListWidget::item {{ padding:6px 10px; border-radius:4px; margin:2px 0; }}"
            f"QListWidget::item:selected {{ background:{COLORS['accent']}; color:#fff; }}"
        )
        left_layout.addWidget(self._list)
        splitter.addWidget(left)

        # 右侧详情
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._detail_stack = QWidget()
        detail_layout = QVBoxLayout(self._detail_stack)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)

        # 问题
        detail_layout.addWidget(QLabel("问题："))
        self._question_label = QLabel("")
        self._question_label.setWordWrap(True)
        self._question_label.setStyleSheet(
            f"background:{COLORS['surface3']}; color:{COLORS['text']}; "
            f"border-radius:4px; padding:6px 10px;"
        )
        detail_layout.addWidget(self._question_label)

        # AI 润色结果（可编辑）
        detail_layout.addWidget(QLabel("AI 修改结果（可直接编辑）："))
        self._content_edit = QTextEdit()
        self._content_edit.setStyleSheet(
            f"QTextEdit {{ background:{COLORS['surface3']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; padding:8px; "
            f"font-size:13px; }}"
        )
        detail_layout.addWidget(self._content_edit, stretch=1)

        # 修正意见摘要
        self._notes_label = QLabel("")
        self._notes_label.setWordWrap(True)
        self._notes_label.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        detail_layout.addWidget(self._notes_label)

        # 状态提示
        self._review_status = QLabel("")
        self._review_status.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        detail_layout.addWidget(self._review_status)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._approve_btn = QPushButton("✓ 通过并入知识库")
        self._approve_btn.setCursor(Qt.PointingHandCursor)
        self._approve_btn.clicked.connect(self._approve)
        self._approve_btn.setStyleSheet(
            f"QPushButton {{ background:{COLORS['accent']}; color:#fff; "
            f"border:none; border-radius:6px; padding:8px 16px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{COLORS['accent2']}; }}"
        )
        btn_row.addWidget(self._approve_btn)

        self._re_refine_btn = QPushButton("🔄 AI 再次润色")
        self._re_refine_btn.setCursor(Qt.PointingHandCursor)
        self._re_refine_btn.clicked.connect(self._re_refine)
        self._re_refine_btn.setStyleSheet(
            f"QPushButton {{ background:{COLORS['surface2']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; padding:8px 16px; }}"
            f"QPushButton:hover {{ background:{COLORS['accent2']}; color:#fff; "
            f"border-color:{COLORS['accent2']}; }}"
        )
        btn_row.addWidget(self._re_refine_btn)

        self._reject_btn = QPushButton("✗ 拒绝")
        self._reject_btn.setCursor(Qt.PointingHandCursor)
        self._reject_btn.clicked.connect(self._reject)
        self._reject_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{COLORS['danger']}; "
            f"border:1px solid {COLORS['danger']}; border-radius:6px; padding:8px 16px; }}"
            f"QPushButton:hover {{ background:{COLORS['danger']}; color:#fff; }}"
        )
        btn_row.addWidget(self._reject_btn)

        btn_row.addStretch()
        detail_layout.addLayout(btn_row)

        self._detail_stack.hide()
        right_layout.addWidget(self._detail_stack)

        empty_label = QLabel("选择左侧条目进行审核")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet(f"color:{COLORS['muted']};font-size:13px;")
        right_layout.addWidget(empty_label, stretch=1)

        splitter.addWidget(right)
        splitter.setSizes([240, 520])
        layout.addWidget(splitter, stretch=1)

        # ── 历史记录（可折叠） ──
        hist_header = QHBoxLayout()
        self._history_toggle = QPushButton("📋 纠错历史 ▸")
        self._history_toggle.setCursor(Qt.PointingHandCursor)
        self._history_toggle.setFlat(True)
        self._history_toggle.clicked.connect(self._toggle_history)
        self._history_toggle.setStyleSheet(
            f"QPushButton {{ color:{COLORS['muted']}; font-weight:600; "
            f"text-align:left; padding:4px 8px; }}"
        )
        hist_header.addWidget(self._history_toggle)
        hist_header.addStretch()
        layout.addLayout(hist_header)

        self._history_panel = QWidget()
        hist_layout = QVBoxLayout(self._history_panel)
        hist_layout.setContentsMargins(0, 0, 0, 0)
        hist_layout.setSpacing(4)

        self._history_list = QListWidget()
        self._history_list.setMaximumHeight(150)
        self._history_list.currentRowChanged.connect(self._on_history_select)
        self._history_list.setStyleSheet(
            f"QListWidget {{ background:{COLORS['input']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; font-size:11px; }}"
            f"QListWidget::item {{ padding:4px 8px; }}"
            f"QListWidget::item:selected {{ background:{COLORS['accent']}; color:#fff; }}"
        )
        hist_layout.addWidget(self._history_list)

        hist_btn_row = QHBoxLayout()
        hist_btn_row.setSpacing(6)
        self._hist_view_btn = QPushButton("查看详情")
        self._hist_view_btn.clicked.connect(self._view_history_item)
        self._hist_edit_btn = QPushButton("编辑")
        self._hist_edit_btn.clicked.connect(self._edit_history_item)
        self._hist_delete_btn = QPushButton("删除")
        self._hist_delete_btn.clicked.connect(self._delete_history_item)
        for btn in (self._hist_view_btn, self._hist_edit_btn, self._hist_delete_btn):
            btn.setStyleSheet(
                f"QPushButton {{ background:{COLORS['surface2']}; color:{COLORS['text']}; "
                f"border:1px solid {COLORS['border']}; border-radius:4px; padding:3px 10px; "
                f"font-size:11px; }}"
            )
            hist_btn_row.addWidget(btn)
        hist_btn_row.addStretch()
        hist_layout.addLayout(hist_btn_row)

        self._history_panel.hide()
        layout.addWidget(self._history_panel)

    def _refresh_history(self) -> None:
        self._history_items = load_history(self._project_root)
        self._history_list.clear()
        for item in self._history_items:
            q = item.get("question", "")[:50]
            ts = item.get("approved_at", "")[:16]
            self._history_list.addItem(f"[{ts}] {q}")

    def _toggle_history(self) -> None:
        visible = not self._history_panel.isVisible()
        self._history_panel.setVisible(visible)
        self._history_toggle.setText(
            "📋 纠错历史 ▾" if visible else "📋 纠错历史 ▸"
        )
        if visible:
            self._refresh_history()

    def _on_history_select(self, _index: int) -> None:
        pass  # selection handled by button clicks

    def _view_history_item(self) -> None:
        index = self._history_list.currentRow()
        if index < 0:
            return
        item = self._history_items[index]
        QMessageBox.information(
            self, "纠错历史详情",
            f"问题：{item.get('question', '')}\n\n"
            f"审核通过内容：\n{item.get('approved_content', '')}\n\n"
            f"修正意见：{item.get('notes', '')}\n"
            f"通过时间：{item.get('approved_at', '')}",
        )

    def _edit_history_item(self) -> None:
        index = self._history_list.currentRow()
        if index < 0:
            return
        item = self._history_items[index]
        if not _remove_approved_entry(self._project_root, item):
            QMessageBox.warning(
                self,
                "无法撤回",
                "这是一条旧版历史记录，无法自动定位知识库原文。"
                "请先在知识库中手动删除对应条目。",
            )
            return
        # 填回待审区
        new_item = {
            "question": item.get("question", ""),
            "original_answer": item.get("original_answer", ""),
            "refined": item.get("approved_content", ""),
            "notes": item.get("notes", "") + " (从历史撤回重新编辑)",
            "submitted_at": datetime.now().isoformat(),
        }
        items = load_pending(self._project_root)
        items.insert(0, new_item)
        save_pending(self._project_root, items)
        delete_history_item(self._project_root, index)
        self._refresh_list()
        self._refresh_history()
        self.knowledge_changed.emit()
        QMessageBox.information(self, "已撤回", "历史记录已移回待审队列。")

    def _delete_history_item(self) -> None:
        index = self._history_list.currentRow()
        if index < 0:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            "只删除审核历史记录，不会删除已经写入知识库的内容。确认继续？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        delete_history_item(self._project_root, index)
        self._refresh_history()

    def _refresh_list(self) -> None:
        self._items = load_pending(self._project_root)
        self._list.clear()
        for i, item in enumerate(self._items):
            q = item.get("question", "")[:60]
            text = f"[{i+1}] {q}"
            self._list.addItem(text)

    def _on_select(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            self._detail_stack.hide()
            return
        item = self._items[index]
        self._question_label.setText(item.get("question", ""))
        self._content_edit.setPlainText(item.get("refined", ""))
        self._notes_label.setText(f"修正意见：{item.get('notes', '无')}")
        self._detail_stack.show()

    def _approve(self) -> None:
        index = self._list.currentRow()
        if index < 0:
            return
        item = self._items[index]
        content = self._content_edit.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "无法通过", "审核内容不能为空。")
            return

        reply = QMessageBox.question(
            self, "确认通过",
            f"将以下内容写入知识库：\n\n{content[:200]}...\n\n确认？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        _write_approved_entry(self._project_root, item, content)

        # 保存到历史
        item["approved_at"] = datetime.now().isoformat()
        item["approved_content"] = content
        add_to_history(self._project_root, dict(item))

        del self._items[index]
        save_pending(self._project_root, self._items)
        self._refresh_list()
        self._detail_stack.hide()
        self._refresh_history()
        self.knowledge_changed.emit()
        QMessageBox.information(self, "通过", "已写入知识库。请重建索引使新内容可搜索。")

    def _re_refine(self) -> None:
        index = self._list.currentRow()
        if index < 0:
            return
        item = self._items[index]
        current_text = self._content_edit.toPlainText().strip()
        if not current_text:
            return

        # 检查用户是否手动编辑过（跟原始 AI 结果不一致）
        original_refined = item.get("refined", "")
        user_edited = current_text != original_refined
        edit_hint = (
            "用户已在编辑器中手动修改了内容，请保留用户修改的意图并在此基础上润色。"
            if user_edited else ""
        )

        self._review_status.setText("AI 正在润色，请稍候...")
        self._review_status.setStyleSheet(f"color:{COLORS['warning']};font-size:11px;")
        self._re_refine_btn.setEnabled(False)
        self._re_refine_btn.setText("⏳ 润色中...")
        self._review_status.repaint()
        self._re_refine_btn.repaint()

        prompt = (
            f"请优化以下 FAQ 内容，使其更准确、流畅、专业。只输出：\n"
            f"Q: <问题>\nA: <回答>\n\n"
            f"当前内容：\n{current_text}\n\n"
            f"{edit_hint}\n"
            f"原始修正意见（供参考）：{item.get('notes', '')}"
        )
        try:
            refined = self._client.complete(prompt).strip()
            self._content_edit.setPlainText(refined)
            # 更新存储的 refined 内容
            item["refined"] = refined
            save_pending(self._project_root, self._items)
            self._review_status.setText("✓ 润色完成，可直接通过或继续编辑。")
            self._review_status.setStyleSheet(f"color:{COLORS['accent']};font-size:11px;")
        except Exception as e:
            self._review_status.setText(f"✗ 润色失败：{e}")
            self._review_status.setStyleSheet(f"color:{COLORS['danger']};font-size:11px;")
        finally:
            self._re_refine_btn.setEnabled(True)
            self._re_refine_btn.setText("🔄 AI 再次润色")

    def _reject(self) -> None:
        index = self._list.currentRow()
        if index < 0:
            return
        reply = QMessageBox.question(
            self, "确认拒绝",
            "拒绝后该纠错记录将被删除，不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        del self._items[index]
        save_pending(self._project_root, self._items)
        self._refresh_list()
        self._detail_stack.hide()


# ── 提交到审核队列 ────────────────────────────────

def submit_correction(
    project_root: Path,
    question: str,
    original_answer: str,
    refined: str,
    notes: str,
) -> None:
    items = load_pending(project_root)
    items.append(
        {
            "question": question,
            "original_answer": original_answer[:2000],
            "refined": refined,
            "notes": notes,
            "submitted_at": datetime.now().isoformat(),
        }
    )
    save_pending(project_root, items)
