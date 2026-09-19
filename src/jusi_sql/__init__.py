"""Provider-neutral SQL family primitives for Jusi 1.0.

This module intentionally imports neither IPython nor a terminal application.
Catalog discovery can therefore import it without crossing runtime boundaries.
"""

from .catalog import (
    FAMILY_ID,
    MAGIC_NAME,
    SQL_CAPABILITIES,
    SQL_PRESENTATION,
    sql_catalog_entry,
    sql_family_claim,
)
from .completion import (
    CompletionColumn,
    CompletionItem,
    CompletionObject,
    MetadataSnapshot,
    SqlCompletionRequest,
    complete_sql,
    parse_query_relations,
)
from .config import (
    ResolvedSqlTarget,
    SqlConfigError,
    SqlFamilyConfig,
    SqlProviderIdentity,
    SqlTarget,
    resolve_sql_target,
)
from .metadata import MetadataCache, sql_cache_directory
from .visidata import SqlSheetActions, bind_sql_actions, find_sql_actions, install_visidata_commands

__all__ = [
    "FAMILY_ID",
    "MAGIC_NAME",
    "SQL_CAPABILITIES",
    "SQL_PRESENTATION",
    "CompletionColumn",
    "CompletionItem",
    "CompletionObject",
    "MetadataSnapshot",
    "MetadataCache",
    "ResolvedSqlTarget",
    "SqlCompletionRequest",
    "SqlConfigError",
    "SqlFamilyConfig",
    "SqlProviderIdentity",
    "SqlSheetActions",
    "SqlTarget",
    "complete_sql",
    "bind_sql_actions",
    "find_sql_actions",
    "install_visidata_commands",
    "parse_query_relations",
    "resolve_sql_target",
    "sql_catalog_entry",
    "sql_cache_directory",
    "sql_family_claim",
]

__version__ = "0.2.0"
