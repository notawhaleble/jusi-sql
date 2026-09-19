from __future__ import annotations

from types import SimpleNamespace

from jusi_sql.visidata import SqlSheetActions, bind_sql_actions, find_sql_actions, install_visidata_commands


class FakeBaseSheet:
    commands = {}

    @classmethod
    def command(cls, keys, name, help_text, *, replay):
        def decorate(function):
            cls.commands[name] = (keys, help_text, replay, function)
            return function
        return decorate


class FakeVd:
    def __init__(self) -> None:
        self.warnings = []
        self.answer = "0"

    def warning(self, message):
        self.warnings.append(message)

    def input(self, _prompt):
        return self.answer


def test_derived_sheets_keep_provider_owned_actions_without_a_global_session() -> None:
    root = SimpleNamespace(source=None)
    derived = SimpleNamespace(source=root)
    calls = []
    actions = SqlSheetActions(fetch_more=lambda count: calls.append(("fetch", count)) or count)
    bind_sql_actions(root, actions)
    assert find_sql_actions(derived) is actions


def test_shared_visidata_commands_delegate_to_the_owning_provider() -> None:
    FakeBaseSheet.commands = {}
    if hasattr(FakeBaseSheet, "_jusi_sql_family_commands_v1"):
        delattr(FakeBaseSheet, "_jusi_sql_family_commands_v1")
    vd = FakeVd()
    module = SimpleNamespace(BaseSheet=FakeBaseSheet, vd=vd)
    install_visidata_commands(module)
    install_visidata_commands(module)
    assert len(FakeBaseSheet.commands) == 12

    calls = []
    root = SimpleNamespace(source=None)
    derived = SimpleNamespace(source=root)
    bind_sql_actions(root, SqlSheetActions(
        fetch_more=lambda count: calls.append(("fetch", count)) or count,
        commit=lambda: calls.append(("commit",)),
        rollback=lambda: calls.append(("rollback",)),
    ))
    FakeBaseSheet.commands["jusi-sql-fetch-3"][3](derived)
    FakeBaseSheet.commands["jusi-sql-fetch-prompt"][3](derived)
    FakeBaseSheet.commands["jusi-sql-commit"][3](derived)
    FakeBaseSheet.commands["jusi-sql-rollback"][3](derived)
    assert calls == [("fetch", 3), ("fetch", 0), ("commit",), ("rollback",)]
