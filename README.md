# jusi-sql

`jusi-sql` is the independently installable SQL plugin family for Jusi 1.0.
It owns the user-facing `%%sql` contract and the provider-neutral code that
SQLite, PostgreSQL, ClickHouse, and future database plugins should share. It is
not an exact provider and therefore publishes no `jusi.plugins.v1` entry point.

## Family contract

Every exact SQL provider advertises the same catalog claim:

- family `sql`, magic `sql`
- capabilities `execute`, `followup`, `complete`, `interrupt`, and
  `editor_actions`
- shared `sql` syntax and indentation profiles
- terminal-interactive presentation

An exact provider may refine syntax after handoff (for example `pgsql` or
`clickhouse`), but may not change the shared capabilities or presentation.
Providers own connections, transactions, dialect metadata queries,
cancellation, result rendering, selection meaning, and application IPC.

The family owns target configuration and selection, deterministic ownership of
one `%%sql` magic, the initial handoff payload, continuing-operation parsing,
metadata-aware completion, safe cache paths, and private application staging.
There is no process-global live-session registry. A worker and its exact
provider session belong to one client in one notebook-runtime generation.

## Configuration

The canonical 1.0 shape is:

```toml
[sql.targets.warehouse]
provider = "clickhouse"
host = "db.internal"
database = "analytics"

[sql.targets.reporting]
provider = "postgres"
host = "pg.internal"
dbname = "reports"
```

Then a cell starts with `%%sql warehouse`. The provider is resolved only inside
the target kernel against adapters installed in that runtime. Missing, unknown,
unavailable, and ambiguous providers fail without printing target options. The
historical `[sql.warehouse]` shape is accepted during migration, but it cannot
be mixed with `[sql.targets.*]`.

Secrets may be provider options because the target worker needs them. They are
never placed in catalog metadata or error messages. Prefer provider-owned
environment or secret resolution where possible.

## Exact-provider integration

Catalog code stays lightweight:

```python
from jusi_sql import sql_catalog_entry

def catalog_entry():
    return sql_catalog_entry(
        plugin_id="postgres",
        plugin_version="1.0.0",
        distribution="jusi-postgres",
        kernel_extension="jusi_postgres.kernel",
        worker_entry_point="jusi_postgres.worker:create_worker",
        provider_presentation={"syntax": "pgsql", "indent": "sql"},
    )
```

The exact kernel module retains its own attested identity while sharing the
dispatcher:

```python
from jusi_sql.kernel import SqlKernelAdapter

_adapter = SqlKernelAdapter(
    plugin_id="postgres",
    plugin_version="1.0.0",
    selectors=("postgres", "postgresql"),
    empty_sql="SELECT 1 WHERE false",
)

jusi_kernel_adapter_v1 = _adapter.manifest
configure_jusi_runtime_v1 = _adapter.configure
load_ipython_extension = _adapter.load
```

Each installed adapter registers its identity in the shared dispatcher. After
all catalog modules attest, `%%sql` resolves the alias and emits one exact 1.0
handoff. Registration rejects selector collisions and an unrelated extension
already owning `%%sql`; it never relies on import order.

Worker code uses composition rather than the retired handler hierarchy:

```python
from jusi_sql.worker import SqlWorker

def create_worker(context):
    return SqlWorker(context, PostgresSession)
```

`PostgresSession` implements `execute`, `followup`, `complete`, `interrupt`,
`editor_action`, and `close`. `interrupt` is called concurrently and must be
prompt and thread-safe. Recoverable database errors should raise
`jusi.plugin_api.OperationRejected`; broken sessions should fail normally so
Jusi fences the worker.

## Completion and metadata

`complete_sql` consumes a `MetadataSnapshot` and Jusi's full completion payload.
It returns absolute Unicode code-point ranges, preserves suffix text, handles
empty prefixes, and understands schema, table, alias, and column qualification.
Exact providers only collect dialect metadata and supply keyword lists.

`MetadataCache` provides stale-while-refresh snapshots.
`sql_cache_directory` creates stable provider-scoped paths while recursively
redacting secret values from the fingerprint.

Providers using VisiData may install the optional `visidata` extra and use
`SqlSheetActions`, `bind_sql_actions`, and `install_visidata_commands`. This
supplies the common numeric/`gf` fetch and `gc`/`gr` transaction commands on
result sheets and all derived sheets. Live callbacks remain attached to their
own provider sheet; the family does not keep a global current session.

## Migration from 0.x providers

Remove `DisplayHandlerSpec`, `BaseSqlHandler`, `SqlSheetRuntime`, environment
payloads, and the `jusi plugin-runtime` bootstrap. Split each provider into
catalog, kernel adapter, worker, and terminal-application import boundaries.
Keep VisiData and driver imports out of catalog and worker startup.

PostgreSQL- and ClickHouse-specific connection, streaming, binary-value,
Kerberos, transaction, and cancellation code remains in those packages. Their
duplicated target parsing, magic registration, completion models, relation
parsing, metadata cache, safe cache path, and operation dispatch should be
deleted in favor of this family package during their 1.0 migrations.
