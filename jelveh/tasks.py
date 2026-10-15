"""Run blocking API and image work off the UI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Signals(QObject):
    ok = Signal(object)
    err = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as error:  # noqa: BLE001 - surface any worker failure to the UI
            self._emit(self.signals.err, str(error))
            return
        self._emit(self.signals.ok, result)

    def _emit(self, signal, value) -> None:
        try:
            signal.emit(value)
        except RuntimeError:
            return


class TaskRunner(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: set[_Job] = set()

    def run(self, fn, on_ok, on_err=None) -> None:
        job = _Job(fn)
        self._jobs.add(job)
        job.signals.ok.connect(lambda result, job=job: self._succeed(job, on_ok, result))
        job.signals.err.connect(lambda message, job=job: self._fail(job, on_err, message))
        QThreadPool.globalInstance().start(job)

    @Slot()
    def _succeed(self, job: _Job, callback, result) -> None:
        self._jobs.discard(job)
        callback(result)

    @Slot()
    def _fail(self, job: _Job, callback, message: str) -> None:
        self._jobs.discard(job)
        if callback:
            callback(message)
