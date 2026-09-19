from __future__ import annotations

from typing import Any, Iterable, Mapping


FAMILY_ID = "sql"
MAGIC_NAME = "sql"
SQL_CAPABILITIES = ("execute", "followup", "complete", "interrupt", "editor_actions")
SQL_PRESENTATION = {"syntax": "sql", "indent": "sql"}


def sql_family_claim(
    *,
    provider_presentation: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the one canonical catalog claim shared by every SQL provider."""
    claim: dict[str, Any] = {
        "family_id": FAMILY_ID,
        "magic_name": MAGIC_NAME,
        "capabilities": list(SQL_CAPABILITIES),
        "presentation": dict(SQL_PRESENTATION),
    }
    if provider_presentation:
        claim["provider_presentation"] = dict(provider_presentation)
    return claim


def sql_catalog_entry(
    *,
    plugin_id: str,
    plugin_version: str,
    distribution: str,
    kernel_extension: str,
    worker_entry_point: str,
    provider_presentation: Mapping[str, str] | None = None,
    media_types: Iterable[str] = ("text/x-ansi",),
) -> dict[str, Any]:
    """Build an exact-provider catalog entry without importing runtime code."""
    return {
        "plugin_id": _required(plugin_id, "plugin_id"),
        "plugin_version": _required(plugin_version, "plugin_version"),
        "distribution": _required(distribution, "distribution"),
        "families": [sql_family_claim(provider_presentation=provider_presentation)],
        "kernel_extensions": [_required(kernel_extension, "kernel_extension")],
        "worker_entry_point": _required(worker_entry_point, "worker_entry_point"),
        "media_types": list(dict.fromkeys(media_types)),
        "interaction": "terminal_interactive",
    }


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must be a non-empty string")
    return normalized
