from __future__ import annotations

import pytest

from jusi.protocol import validate_completion
from jusi_sql import CompletionColumn, CompletionObject, MetadataSnapshot, complete_sql


SNAPSHOT = MetadataSnapshot(
    schemas=["demo", "public"],
    objects=[
        CompletionObject("accounts", "demo", "table"),
        CompletionObject("users", "public", "table"),
    ],
    columns=[
        CompletionColumn("users", "email", "public", "text"),
        CompletionColumn("users", "id", "public", "integer"),
    ],
    functions=[CompletionObject("lower", "public", "function", "text -> text")],
)


def payload(body: str, cursor: int | None = None) -> dict:
    cursor = len(body) if cursor is None else cursor
    prefix = body[:cursor]
    return {
        "body": body,
        "prefix": prefix,
        "cursor_pos": cursor,
        "cursor_row": prefix.count("\n"),
        "cursor_col": len(prefix.rsplit("\n", 1)[-1]),
    }


def test_empty_relation_prefix_returns_tables_at_empty_absolute_range() -> None:
    request = payload("select * from ")
    result = complete_sql(SNAPSHOT, request, keywords=("SELECT", "FROM"))
    validate_completion(result, request["cursor_pos"])
    assert "users" in {item["text"] for item in result["items"]}
    assert "SELECT" not in {item["text"] for item in result["items"]}
    assert {(item["start"], item["end"]) for item in result["items"]} == {
        (request["cursor_pos"], request["cursor_pos"])
    }


def test_relation_alias_completion_uses_unicode_codepoint_ranges_and_preserves_suffix() -> None:
    body = "-- α\nselect * from public.users u where u.eSUFFIX"
    cursor = body.index("SUFFIX")
    request = payload(body, cursor)
    result = complete_sql(SNAPSHOT, request)
    validate_completion(result, cursor)
    item = next(item for item in result["items"] if item["text"] == "u.email")
    assert body[item["start"] : item["end"]] == "u.e"
    assert body[item["end"] :] == "SUFFIX"


def test_schema_table_column_completion_walks_qualification() -> None:
    result = complete_sql(SNAPSHOT, payload("select public.users.e"))
    assert [item["text"] for item in result["items"]] == ["public.users.email"]


def test_completion_rejects_inconsistent_coordinates() -> None:
    request = payload("select e")
    request["cursor_col"] = 0
    with pytest.raises(ValueError, match="coordinates"):
        complete_sql(SNAPSHOT, request)
