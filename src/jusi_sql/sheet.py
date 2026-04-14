from __future__ import annotations

import curses
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from visidata import BaseSheet, SequenceSheet, Sheet, vd

from jusi.infrastructure.debug_timing import emit_timing


@dataclass
class SqlSheetRuntime:
    alias: str
    provider: str
    complete: Callable[[dict[str, Any]], Sequence[dict[str, Any]]]
    followup: Callable[[dict[str, Any]], None]
    interrupt: Callable[[], None]
    stop: Callable[[], None]


_SQL_API_PATCHED = False
_PENDING_SQL_SHEETS: deque[Any] = deque()


def queue_sql_sheet(sheet: Any) -> None:
    _PENDING_SQL_SHEETS.append(sheet)
    emit_timing(
        "sql.queue_sheet",
        pending_count=len(_PENDING_SQL_SHEETS),
        sheet_type=type(sheet).__name__,
        sheet_name=str(getattr(sheet, "name", "")),
    )
    vd.queueCommand('jusi-sql-open-pending-sheet')
    try:
        curses.ungetch(curses.KEY_RESIZE)
        emit_timing("sql.queue_sheet.wakeup", key="KEY_RESIZE")
    except Exception as exc:
        emit_timing(
            "sql.queue_sheet.wakeup_error",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )


def _sql_runtime(sheet: Any) -> SqlSheetRuntime:
    current = sheet
    seen: set[int] = set()
    while current is not None:
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)
        runtime = getattr(current, "jusi_sql_runtime", None)
        if runtime is not None:
            return runtime
        current = getattr(current, "source", None)
    runtime = getattr(BaseSheet, "jusi_sql_runtime", None)
    if runtime is None:
        raise RuntimeError("No active Jusi SQL runtime is bound to the current VisiData session")
    return runtime


def install_sql_base_sheet_api() -> None:
    global _SQL_API_PATCHED
    if _SQL_API_PATCHED:
        return

    @BaseSheet.api
    def jusi_sql_complete(sheet: Any, payload: dict[str, Any]) -> Sequence[dict[str, Any]]:
        return _sql_runtime(sheet).complete(dict(payload))

    @BaseSheet.api
    def jusi_sql_followup(sheet: Any, payload: dict[str, Any]) -> None:
        _sql_runtime(sheet).followup(dict(payload))

    @BaseSheet.api
    def jusi_sql_interrupt(sheet: Any) -> None:
        _sql_runtime(sheet).interrupt()

    @BaseSheet.api
    def jusi_sql_stop(sheet: Any) -> None:
        _sql_runtime(sheet).stop()

    @BaseSheet.command('', 'jusi-sql-open-pending-sheet', 'open next pending Jusi SQL sheet', replay=False)
    def _jusi_sql_open_pending_sheet(sheet: Any) -> None:
        emit_timing(
            "sql.open_pending_sheet.start",
            pending_count=len(_PENDING_SQL_SHEETS),
            active_sheet=type(sheet).__name__,
            active_sheet_name=str(getattr(sheet, "name", "")),
        )
        if not _PENDING_SQL_SHEETS:
            emit_timing("sql.open_pending_sheet.empty")
            return
        next_sheet = _PENDING_SQL_SHEETS.popleft()
        vd.push(next_sheet)
        next_sheet.ensureLoaded()
        emit_timing(
            "sql.open_pending_sheet.done",
            pending_count=len(_PENDING_SQL_SHEETS),
            next_sheet_type=type(next_sheet).__name__,
            next_sheet_name=str(getattr(next_sheet, "name", "")),
            active_sheet_name=str(getattr(vd.activeSheet, "name", "")),
        )

    _SQL_API_PATCHED = True


class BaseSqlSheet(SequenceSheet):
    def bind_sql_runtime(self, runtime: SqlSheetRuntime) -> None:
        self.jusi_sql_runtime = runtime
        BaseSheet.jusi_sql_runtime = runtime

    @Sheet.api
    def execute_complete(self, payload: dict[str, Any]) -> Sequence[dict[str, Any]]:
        return self.jusi_sql_complete(payload)

    @Sheet.api
    def execute_followup(self, payload: dict[str, Any]) -> None:
        self.jusi_sql_followup(payload)

    @Sheet.api
    def execute_interrupt(self) -> None:
        self.jusi_sql_interrupt()

    @Sheet.api
    def execute_stop(self) -> None:
        self.jusi_sql_stop()
