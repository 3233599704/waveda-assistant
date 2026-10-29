"""
多会话管理器 — 创建/切换/删除会话，持久化到 data/conversations.json
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Keep the visible/local conversation substantially longer than the prompt sent
# to the model. Prompt budgeting is handled separately by prompt_builder.py.
MAX_HISTORY_TURNS = 200
MAX_SESSIONS = 50
STOPPED_ANSWER_LABELS = {"已停止生成", "Generation stopped"}


def _is_stopped_answer(answer: object) -> bool:
    lines = [line.strip().lstrip("> ").strip() for line in str(answer).splitlines()]
    return bool(lines and lines[-1] in STOPPED_ANSWER_LABELS)


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = "新对话"
    messages: list[tuple[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    pinned_at: str | None = None
    attachment_paths: list[str] = field(default_factory=list)


class SessionManager:

    def __init__(self, data_dir: Path) -> None:
        self._file = data_dir / "conversations.json"
        self._sessions: dict[str, Session] = {}
        self._current_id: str = ""
        self._load()

    @property
    def current(self) -> Session | None:
        return self._sessions.get(self._current_id)

    @property
    def current_id(self) -> str:
        return self._current_id

    @property
    def sessions(self) -> dict[str, Session]:
        return self._sessions

    def new_session(self) -> Session:
        if len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.created_at)
            del self._sessions[oldest.id]
        session = Session()
        self._sessions[session.id] = session
        self._current_id = session.id
        self._save()
        return session

    def switch_to(self, session_id: str) -> Session | None:
        if session_id in self._sessions:
            self._current_id = session_id
            return self._sessions[session_id]
        return None

    def delete(self, session_id: str) -> bool:
        if session_id not in self._sessions or len(self._sessions) <= 1:
            return False
        previous_sessions = dict(self._sessions)
        previous_current_id = self._current_id
        del self._sessions[session_id]
        if self._current_id == session_id:
            self._current_id = self.sorted_sessions()[0].id
        try:
            self._save()
        except OSError:
            self._sessions = previous_sessions
            self._current_id = previous_current_id
            raise
        return True

    def add_message(self, question: str, answer: str) -> None:
        if not self.current:
            return
        self.current.messages.append((question, answer))
        if len(self.current.messages) > MAX_HISTORY_TURNS:
            self.current.messages = self.current.messages[-MAX_HISTORY_TURNS:]
        self._save()

    def delete_messages(self, indices: Sequence[int]) -> int:
        """Delete selected turns from the current session and persist atomically."""
        session = self.current
        if session is None:
            return 0
        selected = {
            index
            for index in indices
            if isinstance(index, int) and 0 <= index < len(session.messages)
        }
        if not selected:
            return 0

        previous = list(session.messages)
        session.messages = [
            message
            for index, message in enumerate(session.messages)
            if index not in selected
        ]
        try:
            self._save()
        except OSError:
            session.messages = previous
            raise
        return len(selected)

    def rename(self, session_id: str, title: str) -> bool:
        session = self._sessions.get(session_id)
        clean_title = title.strip()
        if session is None or not clean_title:
            return False
        previous = session.title
        session.title = clean_title
        try:
            self._save()
        except OSError:
            session.title = previous
            raise
        return True

    def set_title(self, title: str) -> None:
        if self.current:
            self.rename(self.current.id, title)

    def set_pinned(
        self,
        session_id: str,
        pinned: bool,
        *,
        pinned_at: str | None = None,
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        next_value = (
            session.pinned_at or pinned_at or datetime.now().isoformat()
            if pinned
            else None
        )
        previous = session.pinned_at
        session.pinned_at = next_value
        try:
            self._save()
        except OSError:
            session.pinned_at = previous
            raise
        return True

    def sorted_sessions(self) -> list[Session]:
        pinned = sorted(
            (session for session in self._sessions.values() if session.pinned_at),
            key=lambda session: session.pinned_at or "",
            reverse=True,
        )
        normal = sorted(
            (session for session in self._sessions.values() if not session.pinned_at),
            key=lambda session: session.created_at,
            reverse=True,
        )
        return pinned + normal

    def get_history(self, session_id: str | None = None) -> list[tuple[str, str]]:
        sid = session_id or self._current_id
        session = self._sessions.get(sid)
        return list(session.messages) if session else []

    def attachments_dir(self, session_id: str) -> Path:
        return self._file.parent / "sessions" / "attachments" / session_id

    def _save(self) -> None:
        data = {sid: {"id": s.id, "title": s.title, "messages": s.messages,
                      "created_at": s.created_at, "pinned_at": s.pinned_at,
                      "attachment_paths": s.attachment_paths}
                for sid, s in self._sessions.items()}
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._file.exists():
            self.new_session()
            return
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
            for sid, data in raw.items():
                messages = [
                    tuple(message[:2])
                    for message in data.get("messages", [])
                    if isinstance(message, (list, tuple))
                    and len(message) >= 2
                    and not _is_stopped_answer(message[1])
                ]
                attachment_paths = data.get("attachment_paths", [])
                if not isinstance(attachment_paths, list):
                    attachment_paths = []
                self._sessions[sid] = Session(
                    id=data.get("id", sid), title=data.get("title", "新对话"),
                    messages=messages[-MAX_HISTORY_TURNS:],
                    attachment_paths=attachment_paths,
                    created_at=data.get("created_at", ""),
                    pinned_at=(
                        data.get("pinned_at")
                        if isinstance(data.get("pinned_at"), str) and data.get("pinned_at")
                        else None
                    ),
                )
        except Exception:
            pass
        # 清理空白会话（启动时自动删除没聊过的对话）
        non_empty = {sid: s for sid, s in self._sessions.items() if s.messages}
        if non_empty:
            self._sessions = non_empty
        elif self._sessions:
            # 全是空的，保留一个最新的
            newest = max(self._sessions.values(), key=lambda s: s.created_at)
            self._sessions = {newest.id: newest}

        if not self._sessions:
            self.new_session()
        else:
            self._current_id = next(iter(self._sessions))
        self._save()
