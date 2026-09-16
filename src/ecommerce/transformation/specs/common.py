"""Text helpers shared by every extractor: normalise, look up the attribute table,
and the `Found` result (value + where it came from).

Priority order used by all extractors:
    1. the seller's attribute table (most deliberate)
    2. variant option names ("Đen - 500ml")
    3. the title
    4. the description (longest, noisiest)"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def norm(text: str | None) -> str:
    """Lowercase + NFC. Keeps Vietnamese diacritics (they carry meaning here:
    'ly' is a cup, 'lý' is not)."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", str(text)).lower()


def attr_lookup(attrs: dict[str, str], *names: str) -> str | None:
    """Case-insensitive lookup in the attribute table by any of `names`."""
    for want in names:
        want_n = norm(want)
        for key, value in attrs.items():
            if norm(key) == want_n and value not in (None, ""):
                return str(value).strip()
    return None


@dataclass
class Found:
    value: str | None = None
    source: str | None = None          # "thuộc tính" | "phân loại" | "tiêu đề" | "mô tả"
    extra: dict = field(default_factory=dict)
