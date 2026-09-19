from __future__ import annotations

from pathlib import Path

import pytest

from jusi.plugin_api import OperationRejected, WorkerContext, WorkerResult
from jusi_sql import CompletionItem
from jusi_sql.metadata import sql_cache_directory
from jusi_sql.worker import SqlWorker


def context() -> WorkerContext:
    return WorkerContext("worker_1", "runtime_1", "postgres", "sql", "client_1", "execution_1")


class Session:
    def __init__(self, _context) -> None:
        self.interrupted = False
        self.closed = False

    def execute(self, request):
        return WorkerResult({"alias": request.alias})

    def followup(self, body):
        if body == "bad sql":
            raise OperationRejected("database rejected statement", reason="plugin_error")
        return {"body": body}

    def complete(self, request):
        return [CompletionItem("email", request.cursor_pos - 1, request.cursor_pos, kind="column")]

    def interrupt(self):
        self.interrupted = True

    def editor_action(self, action, selection):
        return WorkerResult({"action": action, "selection": selection})

    def close(self):
        self.closed = True


def test_worker_routes_the_full_sql_operation_contract() -> None:
    worker = SqlWorker(context(), Session)
    assert worker.handle("execute", {"alias": "main", "sql": "select 1", "options": {}}).result == {"alias": "main"}
    assert worker.handle("followup", {"body": "select 2"}).result == {"body": "select 2"}
    completion_payload = {
        "body": "select eSUFFIX", "prefix": "select e", "cursor_pos": 8,
        "cursor_row": 0, "cursor_col": 8,
    }
    assert worker.handle("complete", completion_payload).result["items"][0] == {
        "text": "email", "start": 7, "end": 8, "kind": "column",
    }
    worker.interrupt()
    assert worker._session.interrupted is True
    worker.close()
    assert worker._session.closed is True


def test_cache_fingerprint_redacts_nested_secret_values(tmp_path: Path) -> None:
    one = sql_cache_directory(
        "postgres", "main", {"host": "db", "auth": {"password": "one"}}, state_home=tmp_path,
    )
    two = sql_cache_directory(
        "postgres", "main", {"host": "db", "auth": {"password": "two"}}, state_home=tmp_path,
    )
    assert one == two
    assert str(one).startswith(str(tmp_path / "plugins" / "postgres" / "main"))


def test_recoverable_error_and_other_client_cleanup_preserve_healthy_sessions() -> None:
    first = SqlWorker(context(), Session)
    second_context = WorkerContext(
        "worker_2", "runtime_1", "clickhouse", "sql", "client_2", "execution_2"
    )
    second = SqlWorker(second_context, Session)
    for worker in (first, second):
        worker.handle("execute", {"alias": "main", "sql": "select 1", "options": {}})

    with pytest.raises(OperationRejected, match="database rejected"):
        first.handle("followup", {"body": "bad sql"})
    assert first.handle("followup", {"body": "select 2"}).result == {"body": "select 2"}

    first.close()
    assert second.handle("followup", {"body": "select 3"}).result == {"body": "select 3"}
