from __future__ import annotations

import pytest

from jusi.protocol import validate_plugin_kernel_message
from jusi_sql.config import SqlConfigError
from jusi_sql.kernel import SqlKernelAdapter, _reset_runtime_for_tests, dispatch_sql


class FakeMagics:
    def __init__(self) -> None:
        self.magics = {"cell": {}}


class FakeIp:
    def __init__(self) -> None:
        self.magics_manager = FakeMagics()
        self.registrations = []

    def register_magic_function(self, function, *, magic_kind, magic_name) -> None:
        self.magics_manager.magics[magic_kind][magic_name] = function
        self.registrations.append((magic_kind, magic_name))


@pytest.fixture(autouse=True)
def clean_runtime():
    _reset_runtime_for_tests()
    yield
    _reset_runtime_for_tests()


def test_two_adapters_share_one_dispatcher_and_route_exactly() -> None:
    configuration = {
        "sql": {"targets": {
            "events": {"provider": "clickhouse", "host": "ch"},
            "users": {"provider": "postgres", "host": "pg"},
        }}
    }
    postgres = SqlKernelAdapter(
        plugin_id="postgres", plugin_version="1.0.0", selectors=("postgres",),
        empty_sql="SELECT 1 WHERE false",
    )
    clickhouse = SqlKernelAdapter(
        plugin_id="clickhouse", plugin_version="1.0.0", selectors=("clickhouse",),
        empty_sql="SELECT 1 WHERE 0",
    )
    ipython = FakeIp()
    for adapter in (postgres, clickhouse):
        adapter.configure(configuration)
        adapter.load(ipython)

    assert ipython.registrations == [("cell", "sql")]
    clickhouse_handoff = dispatch_sql("events", "select 42")
    validate_plugin_kernel_message(clickhouse_handoff)
    assert clickhouse_handoff["plugin_id"] == "clickhouse"
    assert clickhouse_handoff["payload"] == {
        "alias": "events", "sql": "select 42", "options": {"host": "ch"},
    }
    postgres_handoff = dispatch_sql("users", "\n")
    assert postgres_handoff["plugin_id"] == "postgres"
    assert postgres_handoff["payload"]["sql"] == "SELECT 1 WHERE false"


def test_unavailable_provider_is_rejected_after_all_installed_adapters_are_known() -> None:
    adapter = SqlKernelAdapter(plugin_id="postgres", plugin_version="1.0.0")
    adapter.configure({"sql": {"targets": {"main": {"provider": "clickhouse"}}}})
    adapter.load(FakeIp())
    with pytest.raises(SqlConfigError) as error:
        dispatch_sql("main", "select 1")
    assert error.value.reason == "unavailable_provider"


def test_registration_rejects_duplicate_provider_selectors() -> None:
    first = SqlKernelAdapter(plugin_id="one", plugin_version="1", selectors=("shared",))
    second = SqlKernelAdapter(plugin_id="two", plugin_version="1", selectors=("shared",))
    ipython = FakeIp()
    first.configure({})
    first.load(ipython)
    second.configure({})
    with pytest.raises(RuntimeError, match="selectors are ambiguous"):
        second.load(ipython)


def test_full_runtime_reset_accepts_reloaded_configuration() -> None:
    first = SqlKernelAdapter(plugin_id="postgres", plugin_version="1.0.0")
    first.configure({"sql": {"targets": {"main": {"provider": "postgres", "host": "old"}}}})
    first.load(FakeIp())
    assert dispatch_sql("main", "select 1")["payload"]["options"]["host"] == "old"

    _reset_runtime_for_tests()
    restarted = SqlKernelAdapter(plugin_id="postgres", plugin_version="1.0.0")
    restarted.configure({"sql": {"targets": {"main": {"provider": "postgres", "host": "new"}}}})
    restarted.load(FakeIp())
    assert dispatch_sql("main", "select 1")["payload"]["options"]["host"] == "new"


def test_adapters_reject_inconsistent_configuration_snapshots() -> None:
    first = SqlKernelAdapter(plugin_id="postgres", plugin_version="1.0.0")
    second = SqlKernelAdapter(plugin_id="clickhouse", plugin_version="1.0.0")
    first.configure({})
    first.load(FakeIp())
    second.configure({"sql": {"targets": {}}})
    with pytest.raises(RuntimeError, match="inconsistent runtime configuration"):
        second.load(FakeIp())
