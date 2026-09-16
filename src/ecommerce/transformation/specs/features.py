"""Feature flags (hours hot / cold, straw, leak-proof...) from title + description."""
from __future__ import annotations

import re

from ecommerce.transformation.specs.common import Found, norm

_HOURS = r"(?:lên (?:đến|tới)\s*|tới\s*|đến\s*)?(\d{1,2})(?:\s*[-–~]\s*(\d{1,2}))?\s*(?:giờ|tiếng|h\b)"
_HOT_RX = re.compile(r"giữ (?:nhiệt|nóng)\s*(?:nóng)?[^.\n;|]{0,15}?" + _HOURS)
_COLD_RX = re.compile(r"giữ (?:lạnh|đá)[^.\n;|]{0,15}?" + _HOURS)

# Built-in flag vocabulary (drinkware oriented); a domain profile may replace it.
DEFAULT_FLAGS: list[tuple[str, str]] = [
    (r"hiển thị nhiệt độ|màn hình led|đèn led|cảm (?:biến|ứng) nhiệt|báo nhiệt", "Hiển thị nhiệt độ"),
    (r"ống hút|with straw|\bstraw\b", "Có ống hút"),
    (r"chống (?:tràn|rò|rỉ|đổ)|chống rò rỉ|kín nước|leak[- ]?proof", "Chống tràn"),
    (r"quai (?:xách|cầm)|tay cầm|dây (?:đeo|xách)|\bquai\b|with handle", "Có quai / tay cầm"),
    (r"nắp bật|nút bấm|bật nắp", "Nắp bật"),
    (r"lõi lọc|lọc trà|lưới lọc|ngăn lọc|lọc bã", "Có lọc trà"),
    (r"bpa[ -]?free|không (?:chứa )?bpa", "Không BPA"),
    (r"khắc (?:tên|laser|chữ)|in tên|in logo|custom product: yes", "Khắc / in tên"),
    (r"chân không", "Cách nhiệt chân không"),
    (r"(?:2|hai) lớp", "2 lớp"),
    (r"(?:3|ba) lớp", "3 lớp"),
    (r"chống trượt|đế silicone?", "Đế chống trượt"),
    (r"xe hơi|ô tô|oto|hộc xe", "Vừa hộc để cốc ô tô"),
    (r"máy rửa bát|máy rửa chén|dishwasher", "Dùng được máy rửa bát"),
    (r"(?:có )?vạch chia|vạch đo", "Có vạch chia"),
    (r"túi (?:đựng|bọc)|kèm túi|tặng túi", "Kèm túi đựng"),
]


def extract_feature_groups(title, description, groups: dict[str, list[tuple[str, str]]],
                           title_only: list[str] | None = None, first_match: list[str] | None = None) -> dict[str, str]:
    """Named flag groups -> {group: "label; label"} (groups with no hit are omitted)."""
    full = norm(f"{title or ''}\n{description or ''}")
    only_title = norm(title or "")
    out: dict[str, str] = {}
    for group, rules in groups.items():
        text = only_title if group in (title_only or []) else full
        hits: list[str] = []
        for rx, label in rules:
            if re.search(rx, text) and label not in hits:
                hits.append(label)
                if group in (first_match or []):
                    break
        if hits:
            out[group] = "; ".join(hits)
    return out


def extract_features(title, description, flags=None, hot_hours: bool = True, cold_hours: bool = True) -> Found:
    text = norm(f"{title or ''}\n{description or ''}")
    features: list[str] = []
    hour_rules = ([(_HOT_RX, "Giữ nóng")] if hot_hours else []) + ([(_COLD_RX, "Giữ lạnh")] if cold_hours else [])
    for rx, label in hour_rules:
        m = rx.search(text)
        if m:
            hours = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
            features.append(f"{label} {hours}h")
    for rx, label in (flags if flags is not None else DEFAULT_FLAGS):
        if re.search(rx, text) and label not in features:
            features.append(label)
    return Found("; ".join(features) if features else None, "tiêu đề + mô tả")
