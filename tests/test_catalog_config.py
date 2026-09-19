from __future__ import annotations

import pytest

from jusi.plugin_api import validate_catalog_claims
from jusi_sql import SqlConfigError, SqlFamilyConfig, SqlProviderIdentity, sql_catalog_entry


def provider(plugin_id: str, module: str, *, syntax: str) -> dict:
    return sql_catalog_entry(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        distribution=f"jusi-{plugin_id}",
        kernel_extension=module,
        worker_entry_point=f"jusi_{plugin_id}.worker:create_worker",
        provider_presentation={"syntax": syntax, "indent": "sql"},
    )


def test_two_exact_providers_make_compatible_family_claims() -> None:
    catalog = {
        "protocol_version": 1,
        "catalog_version": 1,
        "discovery_id": "sql_test",
        "plugins": [
            provider("postgres", "jusi_postgres.kernel", syntax="pgsql"),
            provider("clickhouse", "jusi_clickhouse.kernel", syntax="clickhouse"),
        ],
    }
    validated = validate_catalog_claims(catalog)
    assert [item["plugin_id"] for item in validated["plugins"]] == ["postgres", "clickhouse"]


def test_disagreement_between_sql_family_claims_rejects_the_catalog() -> None:
    postgres = provider("postgres", "jusi_postgres.kernel", syntax="pgsql")
    clickhouse = provider("clickhouse", "jusi_clickhouse.kernel", syntax="clickhouse")
    clickhouse["families"][0]["capabilities"].remove("interrupt")
    catalog = {
        "protocol_version": 1,
        "catalog_version": 1,
        "discovery_id": "sql_conflict",
        "plugins": [postgres, clickhouse],
    }
    with pytest.raises(ValueError, match="Conflicting family claim"):
        validate_catalog_claims(catalog)


def test_config_resolves_canonical_and_legacy_shapes() -> None:
    providers = [SqlProviderIdentity.create("postgres", "1.0.0", ("postgres", "postgresql"))]
    canonical = SqlFamilyConfig.from_mapping({
        "sql": {"targets": {"reports": {"provider": "postgresql", "password": "secret"}}}
    })
    resolved = canonical.resolve("reports", providers)
    assert resolved.plugin_id == "postgres"
    assert resolved.options == {"password": "secret"}

    legacy = SqlFamilyConfig.from_mapping({"sql": {"reports": {"provider": "postgres"}}})
    assert legacy.resolve("reports", providers).plugin_id == "postgres"


def test_config_rejects_missing_unknown_unavailable_and_ambiguous_aliases() -> None:
    config = SqlFamilyConfig.from_mapping({"sql": {"targets": {"main": {"provider": "database"}}}})
    with pytest.raises(SqlConfigError, match="requires a target alias") as missing:
        config.resolve("", [])
    assert missing.value.reason == "missing_alias"
    with pytest.raises(SqlConfigError, match="Unknown SQL target") as unknown:
        config.resolve("other", [])
    assert unknown.value.reason == "unknown_alias"
    with pytest.raises(SqlConfigError, match="unavailable provider") as unavailable:
        config.resolve("main", [])
    assert unavailable.value.reason == "unavailable_provider"

    providers = [
        SqlProviderIdentity.create("one", "1", ("database",)),
        SqlProviderIdentity.create("two", "1", ("database",)),
    ]
    with pytest.raises(SqlConfigError, match="ambiguous provider") as ambiguous:
        config.resolve("main", providers)
    assert ambiguous.value.reason == "ambiguous_provider"


def test_config_does_not_mix_canonical_and_legacy_targets() -> None:
    with pytest.raises(SqlConfigError, match="Do not mix"):
        SqlFamilyConfig.from_mapping({
            "sql": {
                "targets": {"one": {"provider": "postgres"}},
                "two": {"provider": "clickhouse"},
            }
        })
