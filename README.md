# jusi-sql

`jusi-sql` is the shared SQL integration layer for Jusi plugins.

It is not a concrete plugin by itself. Concrete provider packages such as
`jusi-sqlite` are expected to depend on it and expose actual Jusi display
handlers.

This package provides:

- shared `%%sql` kernel extension support
- config resolution from session-scoped Jusi config injected at session/kernel start
- shared SQL handler base on top of `jusi.BaseVdHandler`
- VisiData base-sheet patching so SQL actions still work from derived sheets
