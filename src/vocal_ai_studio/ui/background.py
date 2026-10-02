# Las referencias al hilo y al worker deben mantenerse vivas hasta la señal `finished`,
# o Qt destruye el objeto C++ mientras el hilo todavía lo usa y la app se cierra de golpe.

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

log = logging.getLogger(__name__)


class _Worker(QObject):
    progressed = Signal(float, str)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, job: Callable):
        super().__init__()
        self._job = job
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def is_cancelled(self) -> bool:
        return self._stop

    def run(self) -> None:
        try:
            try:
                result = self._job(self.progressed.emit, self.is_cancelled)
            except Exception as exc:  # noqa: BLE001
                # Las cancelaciones se reconocen por el nombre de la excepción para no acoplar
                # este módulo genérico a una excepción concreta de cada tarea (SearchCancelled,
                # AnalysisCancelled...).
                if type(exc).__name__.endswith("Cancelled"):
                    self.cancelled.emit()
                else:
                    log.exception("Fallo en la tarea en segundo plano")
                    self.failed.emit(exc)
            else:
                self.succeeded.emit(result)
        finally:
            self.finished.emit()


class BackgroundTask:
    def __init__(self) -> None:
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(
        self,
        job: Callable,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        on_success: Callable[[object], None] | None = None,
        on_failure: Callable[[Exception], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        if self._thread is not None:
            return
        thread = QThread()
        worker = _Worker(job)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        thread.started.connect(worker.run)
        if on_progress:
            worker.progressed.connect(on_progress)
        if on_success:
            worker.succeeded.connect(on_success)
        if on_failure:
            worker.failed.connect(on_failure)
        if on_cancelled:
            worker.cancelled.connect(on_cancelled)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._on_thread_finished(on_finished))
        thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def wait(self, timeout_ms: int = 5000) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(timeout_ms)

    def _on_thread_finished(self, on_finished: Callable[[], None] | None) -> None:
        thread, worker = self._thread, self._worker
        self._thread = self._worker = None
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        if on_finished:
            on_finished()
