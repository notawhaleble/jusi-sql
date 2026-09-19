from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SqlProviderIdentity:
    plugin_id: str
    plugin_version: str
    selectors: tuple[str, ...]

    @classmethod
    def create(
        cls,
        plugin_id: str,
        plugin_version: str,
        selectors: Iterable[str] = (),
    ) -> "SqlProviderIdentity":
        normalized_id = _nonempty(plugin_id, "plugin_id")
        normalized = tuple(dict.fromkeys(_nonempty(item, "provider selector") for item in selectors))
        return cls(normalized_id, _nonempty(plugin_version, "plugin_version"), normalized or (normalized_id,))


@dataclass(frozen=True)
class SqlTarget:
    alias: str
    provider: str
    options: dict[str, Any]


@dataclass(frozen=True)
class ResolvedSqlTarget:
    alias: str
    provider: str
    plugin_id: str
    plugin_version: str
    options: dict[str, Any]


class SqlConfigError(ValueError):
    """A secret-safe SQL family configuration error."""

    def __init__(self, message: str, *, reason: str = "invalid_config") -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class SqlFamilyConfig:
    targets: dict[str, SqlTarget]

    @classmethod
    def from_mapping(cls, configuration: Mapping[str, Any] | None) -> "SqlFamilyConfig":
        root = configuration or {}
        if not isinstance(root, Mapping):
            raise SqlConfigError("Jusi runtime configuration must be an object")
        section = root.get("sql")
        if section is None:
            return cls({})
        if not isinstance(section, Mapping):
            raise SqlConfigError("[sql] must be a table")

        # 1.0's canonical shape is [sql.targets.<alias>]. Direct [sql.<alias>]
        # remains accepted so existing target files can migrate independently.
        if "targets" in section:
            raw_targets = section["targets"]
            legacy = [key for key in section if key != "targets"]
            if legacy:
                raise SqlConfigError("Do not mix [sql.targets.*] with legacy [sql.*] targets")
        else:
            raw_targets = section
        if not isinstance(raw_targets, Mapping):
            raise SqlConfigError("[sql.targets] must be a table")

        targets: dict[str, SqlTarget] = {}
        for raw_alias, raw_target in raw_targets.items():
            alias = str(raw_alias).strip()
            if not alias:
                raise SqlConfigError("SQL target aliases must be non-empty")
            if not isinstance(raw_target, Mapping):
                raise SqlConfigError(f"SQL target {alias!r} must be a table")
            provider = str(raw_target.get("provider", "")).strip()
            if not provider:
                raise SqlConfigError(f"SQL target {alias!r} must define provider")
            options = {
                str(key): deepcopy(value)
                for key, value in raw_target.items()
                if str(key) != "provider"
            }
            targets[alias] = SqlTarget(alias, provider, options)
        return cls(targets)

    def resolve(
        self,
        alias: str,
        providers: Iterable[SqlProviderIdentity],
    ) -> ResolvedSqlTarget:
        normalized = str(alias).strip()
        if not normalized:
            raise SqlConfigError("%%sql requires a target alias", reason="missing_alias")
        target = self.targets.get(normalized)
        if target is None:
            raise SqlConfigError(f"Unknown SQL target alias {normalized!r}", reason="unknown_alias")
        matches = [provider for provider in providers if target.provider in provider.selectors]
        if not matches:
            raise SqlConfigError(
                f"SQL target {normalized!r} selects unavailable provider {target.provider!r}",
                reason="unavailable_provider",
            )
        if len(matches) > 1:
            raise SqlConfigError(
                f"SQL target {normalized!r} selects ambiguous provider {target.provider!r}",
                reason="ambiguous_provider",
            )
        provider = matches[0]
        return ResolvedSqlTarget(
            alias=target.alias,
            provider=target.provider,
            plugin_id=provider.plugin_id,
            plugin_version=provider.plugin_version,
            options=deepcopy(target.options),
        )


def resolve_sql_target(
    alias: str,
    configuration: Mapping[str, Any] | None,
    providers: Iterable[SqlProviderIdentity],
) -> ResolvedSqlTarget:
    return SqlFamilyConfig.from_mapping(configuration).resolve(alias, providers)


def _nonempty(value: object, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must be a non-empty string")
    return normalized
