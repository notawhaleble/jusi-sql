from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, TokenList
from sqlparse.tokens import Keyword, Name


RELATION_KEYWORDS = frozenset({"FROM", "JOIN", "INTO", "UPDATE", "TABLE", "VIEW", "DESCRIBE", "DESC"})
_IDENTIFIER_AT_CURSOR = re.compile(
    r'(?:(?:"[^"]*"|`[^`]*`|[A-Za-z_][A-Za-z0-9_$]*)(?:\.(?:"[^"]*"|`[^`]*`|[A-Za-z_][A-Za-z0-9_$]*))*\.?)$'
)


@dataclass(frozen=True)
class CompletionObject:
    name: str
    schema: str = ""
    kind: str = "table"
    detail: str = ""


@dataclass(frozen=True)
class CompletionColumn:
    table: str
    name: str
    schema: str = ""
    data_type: str = ""


@dataclass
class MetadataSnapshot:
    schemas: list[str] = field(default_factory=list)
    objects: list[CompletionObject] = field(default_factory=list)
    columns: list[CompletionColumn] = field(default_factory=list)
    functions: list[CompletionObject] = field(default_factory=list)
    refreshed_at: float = 0.0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MetadataSnapshot":
        return cls(
            schemas=[str(item) for item in payload.get("schemas", ()) if str(item)],
            objects=_objects(payload.get("objects", ()), default_kind="table"),
            columns=_columns(payload.get("columns", ())),
            functions=_objects(payload.get("functions", ()), default_kind="function"),
            refreshed_at=float(payload.get("refreshed_at", 0.0) or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemas": list(self.schemas),
            "objects": [asdict(item) for item in self.objects],
            "columns": [asdict(item) for item in self.columns],
            "functions": [asdict(item) for item in self.functions],
            "refreshed_at": self.refreshed_at,
        }


@dataclass(frozen=True)
class SqlCompletionRequest:
    body: str
    prefix: str
    cursor_pos: int
    cursor_row: int
    cursor_col: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SqlCompletionRequest":
        body = payload.get("body")
        prefix = payload.get("prefix")
        cursor_pos = payload.get("cursor_pos")
        cursor_row = payload.get("cursor_row")
        cursor_col = payload.get("cursor_col")
        if not isinstance(body, str) or not isinstance(prefix, str):
            raise ValueError("SQL completion requires string body and prefix")
        if type(cursor_pos) is not int or not 0 <= cursor_pos <= len(body):
            raise ValueError("SQL completion cursor_pos is outside body")
        if prefix != body[:cursor_pos]:
            raise ValueError("SQL completion prefix does not match body before cursor")
        expected_row = prefix.count("\n")
        expected_col = len(prefix.rsplit("\n", 1)[-1])
        if cursor_row != expected_row or cursor_col != expected_col:
            raise ValueError("SQL completion cursor coordinates are inconsistent")
        return cls(body, prefix, cursor_pos, expected_row, expected_col)


@dataclass(frozen=True)
class CompletionItem:
    text: str
    start: int
    end: int
    label: str = ""
    detail: str = ""
    documentation: str = ""
    kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {"text": self.text, "start": self.start, "end": self.end}
        for key in ("label", "detail", "documentation", "kind"):
            value = getattr(self, key)
            if value:
                item[key] = value
        return item


@dataclass(frozen=True)
class QueryRelation:
    schema: str
    table: str
    alias: str = ""

    @property
    def completion_prefix(self) -> str:
        return self.alias or self.table


def complete_sql(
    snapshot: MetadataSnapshot,
    request: SqlCompletionRequest | Mapping[str, Any],
    *,
    keywords: Iterable[str] = (),
    schema_detail: str = "schema",
    relation_keywords: Iterable[str] = RELATION_KEYWORDS,
) -> dict[str, list[dict[str, Any]]]:
    """Complete SQL using provider metadata and 1.0 absolute source ranges."""
    if not isinstance(request, SqlCompletionRequest):
        request = SqlCompletionRequest.from_payload(request)
    relation_words = {str(item).upper() for item in relation_keywords}
    token, start = _token_at_cursor(request.prefix, relation_words)
    relation_context = _after_relation_keyword(request.prefix, relation_words)
    parts = token.split(".") if token else []
    relations = parse_query_relations(request.prefix)
    items: list[CompletionItem] = []
    seen: set[tuple[str, str]] = set()

    def add(
        text: str,
        kind: str,
        *,
        label: str = "",
        detail: str = "",
        documentation: str = "",
    ) -> None:
        if not _candidate_matches(text, token):
            return
        key = (text, kind)
        if key in seen:
            return
        seen.add(key)
        items.append(CompletionItem(text, start, request.cursor_pos, label or text, detail, documentation, kind))

    if len(parts) <= 1:
        if not relation_context:
            for keyword in keywords:
                add(str(keyword), "keyword", detail="keyword")
        for schema in snapshot.schemas:
            add(schema, "schema", detail=schema_detail)
        for obj in snapshot.objects:
            add(obj.name, obj.kind, detail=obj.schema or obj.detail, documentation=obj.detail)
            if obj.schema:
                add(f"{obj.schema}.{obj.name}", obj.kind, label=obj.name, detail=obj.schema, documentation=obj.detail)
        if not relation_context:
            for function in snapshot.functions:
                add(function.name, "function", detail=function.schema, documentation=function.detail)
            for column in snapshot.columns:
                add(column.name, "column", detail=_column_owner(column), documentation=column.data_type)
    elif len(parts) == 2:
        owner = parts[0].strip('"`').lower()
        for obj in snapshot.objects:
            if obj.schema.lower() == owner:
                add(f"{obj.schema}.{obj.name}", obj.kind, label=obj.name, detail=obj.schema, documentation=obj.detail)
        if not relation_context:
            for function in snapshot.functions:
                if function.schema.lower() == owner:
                    add(f"{function.schema}.{function.name}", "function", label=function.name, detail=function.schema, documentation=function.detail)
            for column in snapshot.columns:
                owners = {column.table.lower()}
                owners.update(relation.completion_prefix.lower() for relation in relations if _relation_matches(column, relation))
                if owner in owners:
                    add(f"{parts[0]}.{column.name}", "column", label=column.name, detail=_column_owner(column), documentation=column.data_type)
    else:
        schema = parts[-3].strip('"`').lower()
        table = parts[-2].strip('"`').lower()
        for column in snapshot.columns:
            if column.schema.lower() == schema and column.table.lower() == table:
                add(f"{'.'.join(parts[:-1])}.{column.name}", "column", label=column.name, detail=_column_owner(column), documentation=column.data_type)

    return {"items": [item.to_dict() for item in items[:500]]}


def parse_query_relations(sql: str) -> list[QueryRelation]:
    relations: list[QueryRelation] = []
    for statement in sqlparse.parse(sql):
        _collect_relations(statement, relations)
    unique: list[QueryRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in relations:
        key = (relation.schema.lower(), relation.table.lower(), relation.alias.lower())
        if key not in seen:
            seen.add(key)
            unique.append(relation)
    return unique


def _candidate_matches(candidate: str, token: str) -> bool:
    if not token:
        return True
    candidate_parts = candidate.lower().split(".")
    token_parts = token.lower().split(".")
    if len(token_parts) == 1:
        return candidate_parts[-1].startswith(token_parts[0]) or candidate.lower().startswith(token.lower())
    if len(candidate_parts) < len(token_parts):
        return False
    return candidate_parts[:-1] == token_parts[:-1] and candidate_parts[-1].startswith(token_parts[-1])


def _token_at_cursor(prefix: str, relation_keywords: set[str]) -> tuple[str, int]:
    if _after_relation_keyword(prefix, relation_keywords):
        return "", len(prefix)
    match = _IDENTIFIER_AT_CURSOR.search(prefix)
    if match is None:
        return "", len(prefix)
    return match.group(0), match.start()


def _after_relation_keyword(prefix: str, relation_keywords: set[str]) -> bool:
    if not prefix or not prefix[-1].isspace():
        return False
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prefix)
    return bool(words and words[-1].upper() in relation_keywords)


def _collect_relations(tokens: TokenList, relations: list[QueryRelation]) -> None:
    values = list(tokens.tokens)
    for index, token in enumerate(values):
        if token.is_group:
            _collect_relations(token, relations)
        normalized = str(getattr(token, "normalized", "") or "").upper()
        if token.ttype is not Keyword or not (normalized in {"FROM", "UPDATE", "INTO", "TABLE"} or normalized.endswith("JOIN")):
            continue
        next_token = _next_meaningful(values[index + 1 :])
        if isinstance(next_token, IdentifierList):
            for identifier in next_token.get_identifiers():
                _append_relation(identifier, relations)
        elif isinstance(next_token, Identifier):
            _append_relation(next_token, relations)
        elif next_token is not None and next_token.ttype in (Name, Keyword):
            relations.append(QueryRelation("", str(next_token.value), ""))


def _append_relation(identifier: Identifier, relations: list[QueryRelation]) -> None:
    if any(token.is_group and token.value.strip().startswith("(") for token in identifier.tokens):
        return
    table = identifier.get_real_name() or ""
    if table:
        relations.append(QueryRelation(identifier.get_parent_name() or "", table, identifier.get_alias() or ""))


def _next_meaningful(tokens: Sequence[Any]) -> Any:
    return next((token for token in tokens if not token.is_whitespace), None)


def _relation_matches(column: CompletionColumn, relation: QueryRelation) -> bool:
    return column.table.lower() == relation.table.lower() and (
        not relation.schema or column.schema.lower() == relation.schema.lower()
    )


def _column_owner(column: CompletionColumn) -> str:
    return f"{column.schema}.{column.table}" if column.schema else column.table


def _objects(values: Any, *, default_kind: str) -> list[CompletionObject]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    result: list[CompletionObject] = []
    for item in values:
        if isinstance(item, Mapping) and str(item.get("name", "")):
            result.append(CompletionObject(
                name=str(item["name"]),
                schema=str(item.get("schema", "")),
                kind=str(item.get("kind", default_kind)) or default_kind,
                detail=str(item.get("detail", "")),
            ))
    return result


def _columns(values: Any) -> list[CompletionColumn]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    result: list[CompletionColumn] = []
    for item in values:
        if isinstance(item, Mapping) and str(item.get("table", "")) and str(item.get("name", "")):
            result.append(CompletionColumn(
                table=str(item["table"]),
                name=str(item["name"]),
                schema=str(item.get("schema", "")),
                data_type=str(item.get("data_type", "")),
            ))
    return result
