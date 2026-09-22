"""Title-based product filter, driven by a domain profile.

A keyword search returns more than the category the user cares about: the
keyword "giữ nhiệt" (keeps heat) also returns lunch boxes, cooler bags, thermal
underwear and baby-food jars. Which nouns to keep and which to drop is domain
knowledge and lives in `configs/domains/<name>.yaml` (`filter:`); this module
only implements the rule.

Rule: the FIRST product noun in the title decides. Sellers put the product
first and the freebies after, so

    "Bình giữ nhiệt 500ml tặng túi"       -> bình     -> keep
    "Túi giữ nhiệt đựng bình sữa"         -> túi      -> drop
    "Hộp cơm giữ nhiệt kèm bình nước"     -> hộp cơm  -> drop

Titles with no noun at all may fall back to a capacity check (`keep_if_capacity`):
a volume in ml / L is a strong hint of a drink vessel ("Stanley Quencher 1.18L").

Freebie tags are removed before the rule runs. Real run 11/09 (TikTok): the
top sellers are titled "[Tặng Túi Canvas Khi Khắc Tên] Ly giữ nhiệt Candy..."
and "<Tặng Túi Giữ Nhiệt> Bình Giữ Nhiệt 1000ml" -- read literally, 'túi'
comes first and 425K-sold cups were dropped as bags.

Without a profile nothing is filtered: every title is kept with an empty
product type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ecommerce.domain.profile import DomainProfile, TitleFilter
from ecommerce.transformation.specs.capacity import capacities_ml
from ecommerce.transformation.specs.common import norm

KEEP_ALL = "không lọc"          # Default reason recorded when no profile is active


@dataclass(frozen=True)
class Verdict:
    """Represents the classification result for a product title.

    Attributes:
        keep: True if the product belongs to the target domain category.
        product_type: The matched noun label (e.g., 'bình', 'ly', 'túi').
        reason: Explanation for keeping or dropping the item.
    """
    keep: bool
    product_type: str
    reason: str


def _first_match(title: str, nouns: list[tuple[str, str]]) -> tuple[int, int, str] | None:
    """Finds the first occurring keyword noun in the product title.

    Args:
        title: Normalized and stripped product title string.
        nouns: List of (regex_pattern, label) tuples from domain profile.

    Returns:
        A tuple of (start_position, -phrase_length, label) or None if no match.
    """
    best: tuple[int, int, str] | None = None
    for rx, label in nouns:
        m = re.search(rx, title)
        if m is None:
            continue
        # Earliest position wins; at the same position, the longer phrase wins.
        candidate = (m.start(), -(m.end() - m.start()), label)
        if best is None or candidate < best:
            best = candidate
    return best


# Pattern matching promotional tags: [..], <..>, (..), {..}, 【..】
_TAGS = re.compile(r"[\[<({【][^\]>)}】]{0,120}[\]>)}】]")


@lru_cache(maxsize=8)
def _freebie_regex(items: tuple[str, ...], qualifiers: tuple[str, ...]) -> re.Pattern | None:
    """Builds regex pattern for detecting freebie mentions (e.g., "tặng kèm túi")."""
    if not items:
        return None
    pattern = (r"(?:tặng|kèm|quà tặng|free)(?:\s+kèm)?(?:\s+\d+)?\s+(?:" + "|".join(items) + ")")
    if qualifiers:
        pattern += r"(?:\s+(?:" + "|".join(qualifiers) + "))?"
    return re.compile(pattern)


def strip_freebies(text: str, spec: TitleFilter | None = None) -> str:
    """Strips promotional tag brackets and freebie gift terms from product title."""
    text = _TAGS.sub(" ", text)
    rx = _freebie_regex(tuple(spec.freebie_items), tuple(spec.freebie_qualifiers)) if spec else None
    if rx is not None:
        text = rx.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify(title: str | None, profile: DomainProfile | None = None) -> Verdict:
    """Evaluates whether to keep or drop a product based on its title and domain rules.

    Step 1: Check if profile exists; if not, keep product.
    Step 2: Clean freebies and promotional tags from title.
    Step 3: Search for target 'keep' nouns vs 'drop' nouns.
    Step 4: Determine verdict based on first-occurring noun or capacity hint.
    """
    if profile is None:
        return Verdict(True, "", KEEP_ALL)

    spec = profile.filter
    full = norm(title)
    text = strip_freebies(full, spec)

    drink = _first_match(text, spec.keep_nouns)
    other = _first_match(text, spec.drop_nouns)

    # Fallback: if entire title was enclosed in promo tags, search full unstripped title
    if drink is None and other is None:
        text = full
        drink = _first_match(text, spec.keep_nouns)
        other = _first_match(text, spec.drop_nouns)

    # Verdict Decision Tree
    if drink and (other is None or drink[:2] <= other[:2]):
        return Verdict(True, drink[2], spec.keep_reason)
    if other:
        return Verdict(False, other[2], f"loại: '{other[2]}' đứng trước")
    if spec.keep_if_capacity and capacities_ml(text):
        return Verdict(True, spec.keep_if_capacity_type, "có dung tích trong tên")
    if not spec.keep_nouns and not spec.drop_nouns:
        return Verdict(True, "", KEEP_ALL)

    return Verdict(False, "Không xác định", "không nhận ra loại sản phẩm")


def title_matches(title: str | None, profile: DomainProfile | None, platform: str) -> bool:
    """Checks if platform-specific title requirement regex passes."""
    if profile is None or not profile.filter.title_must_match:
        return True
    if platform not in profile.filter.title_must_match_platforms:
        return True
    return bool(re.search(profile.filter.title_must_match, norm(title)))


def keep_product(title: str | None, profile: DomainProfile | None, platform: str) -> bool:
    """Main filter entry point returning True if product should be kept in dataset."""
    return title_matches(title, profile, platform) and classify(title, profile).keep
