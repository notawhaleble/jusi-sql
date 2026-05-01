from __future__ import annotations

import json
import os
import sys
from typing import Any, Sequence

from jusi.domain.models import ClientTransport, ExecutableCell
from jusi.plugins import BaseVdHandler, HandlerContext

from .kernel import JUSI_SQL_CONFIG_ENV
from .sheet import install_sql_base_sheet_api


def _normalize_followup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    cell_text = str(normalized.get("cell_text", ""))
    lines = cell_text.splitlines()
    if lines and lines[0].lstrip().startswith("%%sql"):
        normalized["cell_text"] = "\n".join(lines[1:]).lstrip("\n")
    return normalized


def _replace_span(line_text: str, current_word: str) -> tuple[int | None, int | None]:
    if not current_word:
        return None, None
    cursor = len(line_text)
    start = cursor - len(current_word)
    if start < 0:
        return None, None
    if line_text[start:cursor] != current_word:
        start = line_text.rfind(current_word)
        if start < 0:
            return None, None
        cursor = start + len(current_word)
    return start, cursor


def _apply_completion_span(payload: dict[str, Any], items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    line_text = str(payload.get("line_text", ""))
    current_word = str(payload.get("current_word", "")).strip()
    start_col, end_col = _replace_span(line_text.rstrip(), current_word)
    normalized: list[dict[str, Any]] = []
    for item in items:
        current = dict(item)
        if current.get("start_col") is None:
            current["start_col"] = start_col
        if current.get("end_col") is None:
            current["end_col"] = end_col
        normalized.append(current)
    return normalized


class BaseSqlHandler(BaseVdHandler):
    def __init__(self) -> None:
        super().__init__()
        self._payload: dict[str, object] | None = None
        install_sql_base_sheet_api()

    def handle(self, context: HandlerContext, cell: ExecutableCell) -> str:
        self.stop()
        self._mode = "ready"
        self._entry = cell.main_lines[0] if cell.main_lines else f"%%{self.handler_id()}"
        context.append_event(
            {
                "type": "execution_started",
                "cell_id": context.cell_id,
                "kind": cell.kind,
                "syntax": cell.syntax,
                "handler_id": self.handler_id(),
            }
        )
        context.emit_frontend_event(
            "handler_snapshot",
            {
                "handler_id": self.handler_id(),
                "mode": self._mode,
                "entry": self._entry,
                "family": "sql",
                "alias": self.sql_alias(context),
                "provider": self.sql_provider(context),
            },
        )
        self._payload = {
            "content": context.content,
            "meta": dict(context.meta),
        }
        self.prepare_transport(context)
        context.set_status("follow-up")
        context.append_event(
            {
                "type": "execution_finished",
                "status": "follow-up",
                "handler_id": self.handler_id(),
            }
        )
        return "follow-up"

    def sql_alias(self, context: HandlerContext) -> str:
        return str(context.meta.get("alias", "")).strip()

    def sql_provider(self, context: HandlerContext) -> str:
        return str(context.meta.get("provider", "")).strip() or self.handler_id()

    def plugin_runtime_callable(self) -> str:
        raise NotImplementedError

    def terminal_command(self) -> tuple[list[str], str]:
        self._mode = "live"
        return [sys.executable, "-m", "jusi", "plugin-runtime"], ""

    def terminal_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["TERM"] = os.environ.get("JUSI_SQL_TERM", "").strip() or "xterm-256color"
        env["JUSI_PLUGIN_RUNTIME_CALLABLE"] = self.plugin_runtime_callable()
        payload = self._payload or {"content": "", "meta": {}}
        env["JUSI_SQL_PAYLOAD_JSON"] = json.dumps(payload)
        meta = payload.get("meta", {})
        if isinstance(meta, dict):
            session_config = meta.get("session_config")
            if isinstance(session_config, dict):
                env[JUSI_SQL_CONFIG_ENV] = json.dumps(session_config)
        return env

    def snapshot(self) -> dict[str, Any]:
        snapshot = super().snapshot()
        snapshot["family"] = "sql"
        if self._payload is not None:
            snapshot["payload"] = dict(self._payload)
        return snapshot

    def complete(self, context: HandlerContext, payload: dict[str, Any]) -> Sequence[dict[str, Any]]:
        response = context.call_backend_action(
            "plugin_runtime_request",
            {"message_type": "complete", "payload": dict(payload)},
        )
        items = response.get("items", ())
        if isinstance(items, list):
            provider_items = [dict(item) for item in items if isinstance(item, dict)]
            return _apply_completion_span(payload, provider_items)
        return ()

    def followup(self, context: HandlerContext, payload: dict[str, Any]) -> None:
        context.call_backend_action(
            "plugin_runtime_request",
            {"message_type": "followup", "payload": _normalize_followup_payload(payload)},
        )
        return None

    def stop(self) -> None:
        super().stop()
        self._payload = None
