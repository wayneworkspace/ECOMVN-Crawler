"""Shared parser helpers for platform API payload parsing."""
from __future__ import annotations

import re
from typing import Any

_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def _d(v: Any) -> dict:
    """Returns value if it is a dict, else {}."""
    return v if isinstance(v, dict) else {}


def _l(v: Any) -> list:
    """Returns value if it is a list, or [value] if non-empty string/int, else []."""
    if isinstance(v, list):
        return v
    if isinstance(v, (str, int)) and v != "":
        return [v]
    return []


def _s(v: Any) -> str | None:
    """Returns stripped string representation or None."""
    if v is None or isinstance(v, (dict, list)):
        return None
    text = str(v).strip()
    return text or None


def to_int(v: Any) -> int | None:
    """Safely converts raw value to int. Handles formatted strings ('129.000 ₫', '1,234,000')."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            val = float(v)
            if val != val or abs(val) == float("inf"):
                return None
            return int(val)
        except (TypeError, ValueError, OverflowError):
            return None
    s = str(v).replace("\xa0", " ").strip()
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s.split(" ")[0]):
        try:
            return int(digits)
        except (ValueError, OverflowError):
            return None
    m = _NUM.search(s)
    try:
        val = float(m.group(0).replace(",", ".")) if m else None
        if val is None or val != val or abs(val) == float("inf"):
            return None
        return int(val)
    except (TypeError, ValueError, OverflowError):
        return None


def to_float(v: Any) -> float | None:
    """Safely converts raw value to float."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            val = float(v)
            return val if val == val and abs(val) != float("inf") else None
        except (TypeError, ValueError, OverflowError):
            return None
    m = _NUM.search(str(v))
    try:
        val = float(m.group(0).replace(",", ".")) if m else None
        return val if val is not None and val == val and abs(val) != float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None


def first(*values: Any) -> Any:
    """Returns first non-empty, non-None value from candidates."""
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def first_pos(*values: Any) -> Any:
    """Returns first value that is a positive number (> 0)."""
    for v in values:
        num = to_float(v)
        if num is not None and num > 0:
            return v
    return None


def dig(obj: Any, *keys: Any, default: Any = None) -> Any:
    """Safely dig into nested dicts or lists using keys or integer/string indices."""
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list):
            try:
                if str(k).isdigit():
                    idx = int(k)
                    if -len(cur) <= idx < len(cur):
                        cur = cur[idx]
                    else:
                        return default
                else:
                    return default
            except (ValueError, TypeError):
                return default
        else:
            return default
        if cur is None:
            return default
    return cur if cur is not None else default


def deep_find(obj: Any, key: str, max_depth: int = 6) -> Any:
    """Breadth-first search for first non-empty value under `key` in `obj`."""
    frontier = [obj]
    for _ in range(max_depth):
        nxt = []
        for node in frontier:
            if isinstance(node, dict):
                if first(node.get(key)) is not None:
                    return node[key]
                nxt.extend(v for v in node.values() if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                nxt.extend(v for v in node if isinstance(v, (dict, list)))
        frontier = nxt
    return None
