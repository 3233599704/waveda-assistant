from __future__ import annotations

import html

from dataclasses import dataclass
from threading import Event
from typing import Callable
from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class CancellationToken:
    """Thread-safe cooperative cancellation shared by the UI and worker."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

@dataclass(frozen=True)
class AskResult:
    question: str
    answer: RAGAnswer


class WorkerSignals(QObject):
    result = Signal(object)
    progress = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.result.emit(self.fn())
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()
