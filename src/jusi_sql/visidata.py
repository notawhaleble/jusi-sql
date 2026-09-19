from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SqlSheetActions:
    """Provider-owned behavior exposed through shared VisiData commands."""

    fetch_more: Callable[[int], int] | None = None
    commit: Callable[[], None] | None = None
    rollback: Callable[[], None] | None = None


def bind_sql_actions(sheet: Any, actions: SqlSheetActions) -> None:
    """Attach actions to one result sheet without a process-global session."""
    setattr(sheet, "jusi_sql_actions", actions)


def find_sql_actions(sheet: Any) -> SqlSheetActions | None:
    """Find the owning result sheet from a VisiData-derived sheet chain."""
    current = sheet
    seen: set[int] = set()
    while current is not None:
        marker = id(current)
        if marker in seen:
            return None
        seen.add(marker)
        actions = getattr(current, "jusi_sql_actions", None)
        if isinstance(actions, SqlSheetActions):
            return actions
        current = getattr(current, "source", None)
    return None


def install_visidata_commands(visidata_module: Any | None = None) -> None:
    """Install provider-neutral fetch/transaction commands once per application."""
    if visidata_module is None:
        import visidata as visidata_module  # type: ignore[no-redef]
    base_sheet = visidata_module.BaseSheet
    vd = visidata_module.vd
    marker = "_jusi_sql_family_commands_v1"
    if getattr(base_sheet, marker, False):
        return

    def actions_for(sheet: Any) -> SqlSheetActions | None:
        actions = find_sql_actions(sheet)
        if actions is None:
            vd.warning("No SQL result session owns this sheet")
        return actions

    for number in range(1, 10):
        def fetch(sheet: Any, count: int = number) -> None:
            actions = actions_for(sheet)
            if actions is None:
                return
            if actions.fetch_more is None:
                vd.warning("This SQL provider does not support incremental fetch")
                return
            actions.fetch_more(count)

        base_sheet.command(
            str(number),
            f"jusi-sql-fetch-{number}",
            f"fetch {number} more SQL rows",
            replay=False,
        )(fetch)

    @base_sheet.command("gf", "jusi-sql-fetch-prompt", "fetch more SQL rows", replay=False)
    def fetch_prompt(sheet: Any) -> None:
        actions = actions_for(sheet)
        if actions is None:
            return
        if actions.fetch_more is None:
            vd.warning("This SQL provider does not support incremental fetch")
            return
        raw = vd.input("fetch rows (0 for all): ")
        try:
            count = int(str(raw).strip())
        except ValueError:
            vd.warning("Fetch count must be a number")
            return
        if count < 0:
            vd.warning("Fetch count must be at least 0")
            return
        actions.fetch_more(count)

    @base_sheet.command("gc", "jusi-sql-commit", "commit SQL transaction", replay=False)
    def commit(sheet: Any) -> None:
        actions = actions_for(sheet)
        if actions is None:
            return
        if actions.commit is None:
            vd.warning("This SQL provider does not support transactions")
            return
        actions.commit()

    @base_sheet.command("gr", "jusi-sql-rollback", "roll back SQL transaction", replay=False)
    def rollback(sheet: Any) -> None:
        actions = actions_for(sheet)
        if actions is None:
            return
        if actions.rollback is None:
            vd.warning("This SQL provider does not support transactions")
            return
        actions.rollback()

    setattr(base_sheet, marker, True)
