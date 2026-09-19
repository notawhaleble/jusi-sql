from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Union

from jusi.plugin_api import OperationRejected, WorkerContext, WorkerResult

from .completion import CompletionItem, SqlCompletionRequest


@dataclass(frozen=True)
class SqlExecuteRequest:
    alias: str
    sql: str
    options: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SqlExecuteRequest":
        alias = payload.get("alias")
        sql = payload.get("sql")
        options = payload.get("options")
        if not isinstance(alias, str) or not alias.strip():
            raise OperationRejected("SQL execute requires an alias", reason="invalid_request")
        if not isinstance(sql, str):
            raise OperationRejected("SQL execute requires string sql", reason="invalid_request")
        if not isinstance(options, dict):
            raise OperationRejected("SQL execute requires provider options", reason="invalid_request")
        return cls(alias.strip(), sql, dict(options))


class SqlSession(Protocol):
    def execute(self, request: SqlExecuteRequest) -> Union[WorkerResult, dict[str, Any]]: ...
    def followup(self, body: str) -> Union[WorkerResult, dict[str, Any]]: ...
    def complete(self, request: SqlCompletionRequest) -> Any: ...
    def interrupt(self) -> None: ...
    def editor_action(self, action: str, selection: dict[str, Any]) -> WorkerResult: ...
    def close(self) -> None: ...


class SqlWorker:
    """Composition-based 1.0 operation router for one exact SQL session."""

    def __init__(
        self,
        context: WorkerContext,
        session_factory: Callable[[WorkerContext], SqlSession],
    ) -> None:
        self.context = context
        self._session = session_factory(context)
        self._executed = False
        self._closed = False

    def handle(self, operation: str, payload: dict[str, Any]) -> WorkerResult:
        if self._closed:
            raise OperationRejected("SQL session is closed", reason="conflict")
        if operation == "execute":
            if self._executed:
                raise OperationRejected("SQL session was already started", reason="conflict")
            request = SqlExecuteRequest.from_payload(payload)
            result = self._session.execute(request)
            self._executed = True
            return _worker_result(result)
        if not self._executed:
            raise OperationRejected("SQL session has not started", reason="conflict")
        if operation == "followup":
            body = payload.get("body")
            if not isinstance(body, str):
                raise OperationRejected("SQL followup requires string body", reason="invalid_request")
            return _worker_result(self._session.followup(body))
        if operation == "complete":
            try:
                request = SqlCompletionRequest.from_payload(payload)
            except ValueError as exc:
                raise OperationRejected(str(exc), reason="invalid_request") from exc
            completed = self._session.complete(request)
            if isinstance(completed, dict) and isinstance(completed.get("items"), list):
                return WorkerResult(completed)
            items = [item.to_dict() if isinstance(item, CompletionItem) else dict(item) for item in completed]
            return WorkerResult({"items": items})
        if operation == "editor_action":
            action = payload.get("action")
            selection = payload.get("selection")
            if action not in {"copy", "open", "show_diff"} or not isinstance(selection, dict):
                raise OperationRejected("Invalid SQL editor action", reason="invalid_request")
            return self._session.editor_action(action, selection)
        raise OperationRejected(f"Unsupported SQL operation {operation!r}", reason="unsupported")

    def interrupt(self) -> None:
        # Jusi invokes this concurrently. The provider hook must be prompt and
        # thread-safe; this router deliberately takes no ordinary-operation lock.
        if not self._closed:
            self._session.interrupt()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._session.close()


class StagedApplicationPayload:
    """A private, client-owned JSON handoff for a terminal application."""

    def __init__(self, payload: Mapping[str, Any], *, prefix: str = "jusi-sql-") -> None:
        self.directory = Path(tempfile.mkdtemp(prefix=prefix))
        self.directory.chmod(0o700)
        self.path = self.directory / "payload.json"
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(dict(payload), stream, ensure_ascii=False)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def _worker_result(value: Union[WorkerResult, dict[str, Any]]) -> WorkerResult:
    return value if isinstance(value, WorkerResult) else WorkerResult(dict(value))
