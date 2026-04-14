from __future__ import annotations

import json
import os
from typing import Any

from IPython.core.error import UsageError

from jusi.domain.models import JUSI_HANDLER_HANDOFF_MIME
from jusi.infrastructure.debug_timing import emit_timing

from .config import SqlConfigError, get_session_config, resolve_sql_target, set_session_config


JUSI_SQL_CONFIG_ENV = "JUSI_SESSION_CONFIG_JSON"


def register_sql_magic(ipython: Any) -> None:
    cell_magics = getattr(getattr(ipython, "magics_manager", None), "magics", {}).get("cell", {})
    if "sql" in cell_magics:
        return

    def _jusi_sql_magic(line: str, cell: str) -> None:
        from IPython.display import display

        alias = line.strip()
        emit_timing("sql.kernel.magic.invoked", alias=alias, line=line, content_len=len(cell))
        if not alias:
            raise UsageError("%%sql requires a target alias, for example %%sql my_db")
        try:
            target = resolve_sql_target(alias)
        except SqlConfigError as exc:
            emit_timing("sql.kernel.magic.resolve_error", alias=alias, error=str(exc))
            raise UsageError(str(exc)) from exc
        emit_timing("sql.kernel.magic.resolved", alias=target.alias, provider=target.provider)
        payload = {
            "handler_id": target.provider,
            "magic_name": "sql",
            "content": cell,
            "meta": {
                "alias": target.alias,
                "provider": target.provider,
                "line": line,
                "session_config": get_session_config(),
            },
        }
        display(
            {JUSI_HANDLER_HANDOFF_MIME: payload},
            raw=True,
            metadata={JUSI_HANDLER_HANDOFF_MIME: {"alias": target.alias, "provider": target.provider}},
        )
        emit_timing("sql.kernel.magic.handoff_emitted", alias=target.alias, provider=target.provider)

    ipython.register_magic_function(_jusi_sql_magic, magic_kind="cell", magic_name="sql")


def configure_sql_session(config: dict[str, Any] | None) -> None:
    set_session_config(config)
    emit_timing("sql.kernel.session_config", has_config=bool(config), keys=sorted(list((config or {}).keys())))


def load_ipython_extension(ipython: Any) -> None:
    raw = os.environ.get(JUSI_SQL_CONFIG_ENV, "").strip()
    if raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            configure_sql_session(loaded)
    register_sql_magic(ipython)
    emit_timing("sql.kernel.extension_loaded")
