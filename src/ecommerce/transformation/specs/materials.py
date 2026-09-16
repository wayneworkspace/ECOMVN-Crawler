"""Materials, with inner (ruột / lòng) and outer (vỏ) told apart when the text says so."""
from __future__ import annotations

import re
from functools import lru_cache

from ecommerce.transformation.specs.common import Found, attr_lookup, norm

# Built-in vocabulary (drinkware oriented); a domain profile may replace it.
# (regex, canonical name) -- order matters: specific grades before generic.
DEFAULT_MATERIALS: list[tuple[str, str]] = [
    (r"(?:inox|sus|thép(?: không gỉ)?)\s*-?\s*316l?", "Inox 316"),
    (r"(?:inox|sus|thép(?: không gỉ)?)\s*-?\s*304", "Inox 304"),
    (r"(?:inox|sus|thép(?: không gỉ)?)\s*-?\s*201", "Inox 201"),
    (r"thép không gỉ|stainless(?: steel)?|\binox\b", "Inox (không rõ mác)"),
    (r"tritan", "Nhựa Tritan"),
    (r"nhựa\s*pp|\bpp\b", "Nhựa PP"),
    (r"\bpet\b|nhựa pet", "Nhựa PET"),
    (r"nhựa|plastic", "Nhựa"),
    (r"thuỷ tinh|thủy tinh|\bglass\b", "Thủy tinh"),
    (r"gốm sứ|tráng sứ|phủ sứ|lòng sứ|ruột sứ|lõi sứ|ceramic|\bsứ\b|\bgốm\b", "Gốm sứ"),
    (r"titan(?:ium)?", "Titan"),
    (r"\bnhôm\b|aluminium|aluminum", "Nhôm"),
    (r"silicone?", "Silicone"),
    (r"sơn tĩnh điện", "Sơn tĩnh điện"),
    (r"mạ đồng|lớp đồng", "Mạ đồng"),
]
DEFAULT_ATTR_NAMES = ["Chất liệu", "Chất liệu chính", "Material", "Materials",
                      "Chất liệu chai", "Vật liệu", "Chất liệu cốc", "Chất liệu ly"]
DEFAULT_INNER_ATTR_NAMES = ["Chất liệu ruột", "Chất liệu bên trong", "Chất liệu lòng", "Inner Material"]
DEFAULT_OUTER_ATTR_NAMES = ["Chất liệu vỏ", "Chất liệu bên ngoài", "Outer Material"]

_INNER_MARK = r"(?:ruột|lõi|(?<!vui )(?<!hài )lòng|thân trong|lớp trong|bên trong|mặt trong|phần trong|inner)"
_OUTER_MARK = r"(?:vỏ|thân ngoài|lớp ngoài|bên ngoài|mặt ngoài|phần ngoài|thân bình|outer)"
_GAP = r"[^.\n;|]{0,40}?"

Vocabulary = tuple[tuple[str, str], ...]


@lru_cache(maxsize=8)
def _compiled(vocab: Vocabulary) -> tuple[re.Pattern, re.Pattern, re.Pattern]:
    alt = "|".join(f"(?:{rx})" for rx, _ in vocab)
    return (re.compile(_INNER_MARK + _GAP + f"({alt})"),
            re.compile(_OUTER_MARK + _GAP + f"({alt})"),
            re.compile(f"({alt})"))


def _vocab(vocabulary) -> Vocabulary:
    return tuple(tuple(x) for x in (vocabulary or DEFAULT_MATERIALS))


def canonical_material(fragment: str, vocabulary=None) -> str | None:
    fragment = norm(fragment)
    for rx, name in _vocab(vocabulary):
        if re.search(rx, fragment):
            return name
    return None


def _materials_in(text: str, vocab: Vocabulary) -> list[str]:
    names: list[str] = []
    for match in _compiled(vocab)[2].finditer(text):
        name = canonical_material(match.group(1), vocab)
        if name and name not in names:
            names.append(name)
    # "Inox (không rõ mác)" is redundant once a grade is known.
    if any(n.startswith("Inox ") and "không rõ" not in n for n in names):
        names = [n for n in names if "không rõ" not in n]
    return names


def extract_materials(attrs, title, description, vocabulary=None, attribute_names=None,
                      inner_attribute_names=None, outer_attribute_names=None) -> dict[str, Found]:
    """Return {'inner': Found, 'outer': Found, 'all': Found}."""
    vocab = _vocab(vocabulary)
    inner_rx, outer_rx, _ = _compiled(vocab)
    attr_text = " | ".join(filter(None, [
        attr_lookup(attrs, *(attribute_names or DEFAULT_ATTR_NAMES)),
        attr_lookup(attrs, *(inner_attribute_names or DEFAULT_INNER_ATTR_NAMES)),
        attr_lookup(attrs, *(outer_attribute_names or DEFAULT_OUTER_ATTR_NAMES)),
    ]))
    result = {"inner": Found(), "outer": Found(), "all": Found()}
    for source, text in (("thuộc tính", attr_text), ("tiêu đề", title), ("mô tả", description)):
        text = norm(text)
        if not text:
            continue
        if result["inner"].value is None:
            m = inner_rx.search(text)
            if m:
                result["inner"] = Found(canonical_material(m.group(1), vocab), source)
        if result["outer"].value is None:
            m = outer_rx.search(text)
            if m:
                result["outer"] = Found(canonical_material(m.group(1), vocab), source)
        if result["all"].value is None:
            names = _materials_in(text, vocab)
            if names:
                result["all"] = Found(", ".join(names), source)
    return result
