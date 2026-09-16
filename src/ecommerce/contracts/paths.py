"""Read (and, for tests, delete) values in nested JSON by a short path.

    "pdp.data.item.title"          one value
    "pdp.data.item.models[].price" the price of EVERY model (list)
    "ratings[].data.summary"       one value per page in the list
    "skus_price.*.sale_price"      every value of a dict whose keys are ids
    "rating_count.5"               item 5 of a list
    "pdp.data.**.attrs"            'attrs' anywhere below pdp.data (like deep_find)

A value counts as "present" when it is not None / "" / [] / {} -- the same
rule the parsers use (`first()`), so "present" here means "the parser would
use it".
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

DEEP_MAX = 6          # same depth as transform.shopee.common.deep_find


def is_present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _split(path: str) -> list[str]:
    """'a.b[].c' -> ['a', 'b', '[]', 'c']"""
    parts: list[str] = []
    for token in path.split("."):
        if token.endswith("[]"):
            parts.extend([token[:-2], "[]"] if token[:-2] else ["[]"])
        else:
            parts.append(token)
    return parts


def _step(node: Any, head: str) -> list[Any]:
    """The children one path segment leads to."""
    if head == "[]":
        return list(node) if isinstance(node, list) else []
    if head == "*":
        return list(node.values()) if isinstance(node, dict) else []
    if isinstance(node, dict):
        return [node[head]] if head in node else []
    if isinstance(node, list) and head.isdigit() and int(head) < len(node):
        return [node[int(head)]]
    return []


def _descend(node: Any, parts: list[str]) -> Iterator[Any]:
    if not parts:
        yield node
    elif parts[0] == "**":
        yield from _deep(node, parts[1:])
    else:
        for child in _step(node, parts[0]):
            yield from _descend(child, parts[1:])


def _deep(node: Any, rest: list[str]) -> Iterator[Any]:
    """'**.key.more': the FIRST 'key' found breadth-first, like deep_find()."""
    key, after = rest[0], rest[1:]
    frontier = [node]
    for _ in range(DEEP_MAX):
        nxt: list[Any] = []
        for current in frontier:
            if isinstance(current, dict):
                if is_present(current.get(key)):
                    yield from _descend(current[key], after)
                    return
                nxt.extend(v for v in current.values() if isinstance(v, (dict, list)))
            elif isinstance(current, list):
                nxt.extend(v for v in current if isinstance(v, (dict, list)))
        frontier = nxt


def values_at(obj: Any, path: str) -> list[Any]:
    """Every PRESENT value at `path` (empty list = nothing there)."""
    return [v for v in _descend(obj, _split(path)) if is_present(v)]


def delete_at(obj: Any, path: str) -> None:
    """Remove the key(s) at `path` in place. Used by tests to simulate
    'Shopee stopped sending this field'."""
    parts = _split(path)
    parent_parts, last = parts[:-1], parts[-1]
    if last == "**":
        raise ValueError(f"path must not end with '**': {path}")
    if last in ("[]", "*"):                        # every element / every value
        for parent in _descend(obj, parent_parts):
            if isinstance(parent, (list, dict)):
                parent.clear()
        return
    if "**" in parent_parts:
        # every match of the key below that point, not only the first
        i = parent_parts.index("**")
        for base in _descend(obj, parent_parts[:i]):
            _delete_everywhere(base, [*parent_parts[i + 1:], last])
        return
    for parent in _descend(obj, parent_parts):
        if isinstance(parent, dict):
            parent.pop(last, None)
        elif isinstance(parent, list) and last.isdigit() and int(last) < len(parent):
            parent[int(last)] = None


def _delete_everywhere(node: Any, parts: list[str]) -> None:
    if isinstance(node, dict):
        if parts[0] in node:
            if len(parts) == 1:
                node.pop(parts[0])
            else:
                for parent in _descend(node[parts[0]], parts[1:-1]):
                    if isinstance(parent, dict):
                        parent.pop(parts[-1], None)
        for value in list(node.values()):
            _delete_everywhere(value, parts)
    elif isinstance(node, list):
        for value in node:
            _delete_everywhere(value, parts)
