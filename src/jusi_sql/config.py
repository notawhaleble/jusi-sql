from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SqlTargetConfig:
    alias: str
    provider: str
    options: dict[str, object]


class SqlConfigError(RuntimeError):
    pass


_SESSION_CONFIG: dict[str, Any] = {}


def set_session_config(config: Mapping[str, Any] | None) -> None:
    global _SESSION_CONFIG
    if config is None:
        _SESSION_CONFIG = {}
        return
    _SESSION_CONFIG = {str(key): value for key, value in dict(config).items()}


def get_session_config() -> dict[str, Any]:
    return dict(_SESSION_CONFIG)


def resolve_sql_target(alias: str, config: Mapping[str, Any] | None = None) -> SqlTargetConfig:
    normalized = alias.strip()
    if not normalized:
        raise SqlConfigError("%%sql requires a configured target alias")
    root = dict(config) if config is not None else get_session_config()
    sql_section = root.get("sql", {})
    if not isinstance(sql_section, Mapping):
        raise SqlConfigError("Missing [sql] section in the active Jusi session config")
    raw_target = sql_section.get(normalized, {})
    if not isinstance(raw_target, Mapping):
        raise SqlConfigError(f"Invalid [sql.{normalized}] configuration")
    provider = str(raw_target.get("provider", "")).strip()
    if not provider:
        raise SqlConfigError(f"[sql.{normalized}] must define provider")
    options = {str(key): value for key, value in raw_target.items()}
    return SqlTargetConfig(alias=normalized, provider=provider, options=options)
