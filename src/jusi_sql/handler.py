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
            return [dict(item) for item in items if isinstance(item, dict)]
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
