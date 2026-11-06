"""Фоновый импорт источника, чтобы интерфейс не вис."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal


class ImportWorker(QThread):
    progressed = Signal(int)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, db_path: str | Path, path: str | Path,
                 mapping: dict, options: dict | None = None):
        super().__init__()
        self._db_path = str(db_path)
        self._path = str(path)
        self._mapping = dict(mapping)
        self._options = dict(options or {})
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            from core.pool_import import import_source
            from storage.database import connect
            con = connect(self._db_path)
            try:
                res = import_source(
                    con, self._path, self._mapping,
                    sheet=self._options.get("sheet"),
                    header_row=int(self._options.get("header_row", 0)),
                    encoding=self._options.get("encoding", "utf-8-sig"),
                    delimiter=self._options.get("delimiter", "auto"),
                    on_progress=lambda n: self.progressed.emit(int(n)),
                    should_cancel=lambda: self._cancel,
                )
                self.done.emit(dict(res))
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001 — текст уезжает в UI
            self.failed.emit(str(e))
