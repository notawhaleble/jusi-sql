from __future__ import annotations

import shlex
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .catalog import FAMILY_ID, MAGIC_NAME
from .config import SqlConfigError, SqlFamilyConfig, SqlProviderIdentity


HANDOFF_MIME = "application/vnd.jusi.handoff.v1+json"
_DISPATCHER_MARKER = "_jusi_sql_dispatcher_v1"
_providers: dict[str, "SqlKernelAdapter"] = {}
_configuration: dict[str, Any] | None = None


@dataclass(frozen=True)
class SqlMagicArguments:
    alias: str


class SqlKernelAdapter:
    """Exact-provider adapter backed by one shared ``%%sql`` dispatcher."""

    def __init__(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        selectors: Iterable[str] = (),
        empty_sql: str = "",
    ) -> None:
        self.identity = SqlProviderIdentity.create(plugin_id, plugin_version, selectors)
        self.empty_sql = str(empty_sql)
        self._configuration: dict[str, Any] = {}

    def manifest(self) -> dict[str, Any]:
        return {
            "plugin_id": self.identity.plugin_id,
            "plugin_version": self.identity.plugin_version,
            "families": [{"family_id": FAMILY_ID, "magic_name": MAGIC_NAME}],
        }

    def configure(self, configuration: Mapping[str, Any]) -> None:
        if not isinstance(configuration, Mapping):
            raise TypeError("Jusi runtime configuration must be an object")
        self._configuration = deepcopy(dict(configuration))

    def load(self, ipython: Any) -> None:
        _register_provider(self)
        _configure_family(self._configuration)
        _register_dispatcher(ipython)


def parse_sql_magic_line(line: str) -> SqlMagicArguments:
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        raise SqlConfigError(f"Invalid %%sql arguments: {exc}", reason="invalid_magic_line") from exc
    if not parts:
        raise SqlConfigError("%%sql requires a target alias", reason="missing_alias")
    if len(parts) != 1:
        raise SqlConfigError(
            "%%sql accepts one target alias; put provider options in [sql.targets.<alias>]",
            reason="invalid_magic_line",
        )
    return SqlMagicArguments(parts[0])


def dispatch_sql(line: str, cell: str) -> dict[str, Any]:
    arguments = parse_sql_magic_line(line)
    family = SqlFamilyConfig.from_mapping(_configuration)
    target = family.resolve(arguments.alias, (item.identity for item in _providers.values()))
    adapter = _providers[target.plugin_id]
    sql = str(cell)
    if not sql.strip() and adapter.empty_sql:
        sql = adapter.empty_sql
    return {
        "protocol_version": 1,
        "kind": "plugin.handoff",
        "plugin_id": target.plugin_id,
        "plugin_version": target.plugin_version,
        "family_id": FAMILY_ID,
        "magic_name": MAGIC_NAME,
        "payload": {
            "alias": target.alias,
            "sql": sql,
            "options": target.options,
        },
    }


def _register_provider(adapter: SqlKernelAdapter) -> None:
    current = _providers.get(adapter.identity.plugin_id)
    if current is not None and current is not adapter:
        raise RuntimeError(f"SQL provider {adapter.identity.plugin_id!r} registered more than once")
    for existing in _providers.values():
        overlap = set(existing.identity.selectors) & set(adapter.identity.selectors)
        if existing is not adapter and overlap:
            names = ", ".join(sorted(overlap))
            raise RuntimeError(f"SQL provider selectors are ambiguous: {names}")
    _providers[adapter.identity.plugin_id] = adapter


def _configure_family(configuration: Mapping[str, Any]) -> None:
    global _configuration
    candidate = deepcopy(dict(configuration))
    if _configuration is not None and _configuration != candidate:
        raise RuntimeError("SQL adapters received inconsistent runtime configuration")
    _configuration = candidate


def _register_dispatcher(ipython: Any) -> None:
    if getattr(ipython, _DISPATCHER_MARKER, False):
        return
    cell_magics = getattr(getattr(ipython, "magics_manager", None), "magics", {}).get("cell", {})
    if MAGIC_NAME in cell_magics:
        raise RuntimeError("The sql cell magic is already owned by another extension")

    def sql_magic(line: str, cell: str) -> None:
        from IPython.core.error import UsageError
        from IPython.display import display

        try:
            handoff = dispatch_sql(line, cell)
        except SqlConfigError as exc:
            raise UsageError(str(exc)) from exc
        display({HANDOFF_MIME: handoff}, raw=True)

    ipython.register_magic_function(sql_magic, magic_kind="cell", magic_name=MAGIC_NAME)
    setattr(ipython, _DISPATCHER_MARKER, True)


def _reset_runtime_for_tests() -> None:
    global _configuration
    _providers.clear()
    _configuration = None
