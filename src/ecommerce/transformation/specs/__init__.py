"""Specs pulled from free text with regex, one module per attribute.

`extract_specs()` runs the extractors a domain profile enables, the same way
for every platform, and returns the typed `Specs` block of a Product. The
extractors are generic Vietnamese e-commerce text rules; the vocabularies that
are category-specific (materials, feature flags, capacity range) come from the
profile, with built-in defaults for the original drinkware domain.

Without a profile no attribute is extracted (every field stays None).
"""
from __future__ import annotations

from ecommerce.domain.product import Specs
from ecommerce.domain.profile import DomainProfile
from ecommerce.transformation.specs.capacity import capacities_ml, extract_capacity
from ecommerce.transformation.specs.colors import extract_colors, is_color_tier, looks_like_color
from ecommerce.transformation.specs.common import Found, attr_lookup, norm
from ecommerce.transformation.specs.features import extract_feature_groups, extract_features
from ecommerce.transformation.specs.materials import canonical_material, extract_materials
from ecommerce.transformation.specs.origin import extract_origin
from ecommerce.transformation.specs.size import extract_size, extract_weight
from ecommerce.transformation.specs.warranty import extract_warranty

__all__ = [
    "Found",
    "attr_lookup",
    "attributes_text",
    "canonical_material",
    "capacities_ml",
    "extract_capacity",
    "extract_colors",
    "extract_feature_groups",
    "extract_features",
    "extract_materials",
    "extract_origin",
    "extract_size",
    "extract_specs",
    "extract_warranty",
    "extract_weight",
    "is_color_tier",
    "looks_like_color",
    "norm",
]


def attributes_text(attrs: dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in attrs.items())


def extract_specs(attrs: dict[str, str], variant_names: list[str], tiers: list[dict],
                  title: str, description: str, profile: DomainProfile | None = None) -> Specs:
    """attrs = the seller's attribute table; tiers = [{"name", "options"}] variation groups."""
    if profile is None:
        return Specs()
    on = profile.specs.on
    cap_cfg, mat_cfg, feat_cfg = profile.specs.capacity, profile.specs.materials, profile.specs.features
    empty = {"inner": Found(), "outer": Found(), "all": Found()}

    capacity = (extract_capacity(attrs, variant_names, title, description, cap_cfg.min_ml, cap_cfg.max_ml)
                if on("capacity") else Found())
    materials = (extract_materials(attrs, title, description, mat_cfg.vocabulary, mat_cfg.attribute_names,
                                   mat_cfg.inner_attribute_names, mat_cfg.outer_attribute_names)
                 if on("materials") else empty)
    origin = extract_origin(attrs, title, description) if on("origin") else Found()
    warranty = extract_warranty(attrs, title, description) if on("warranty") else Found()
    features = (extract_features(title, f"{attributes_text(attrs)}\n{description}", feat_cfg.flags,
                                 feat_cfg.hot_hours, feat_cfg.cold_hours) if on("features") else Found())
    groups = (extract_feature_groups(title, f"{attributes_text(attrs)}\n{description}", feat_cfg.groups,
                                     feat_cfg.title_only_groups, feat_cfg.first_match_groups)
              if on("features") and feat_cfg.groups else {})
    colors = extract_colors(tiers, attrs, title) if on("colors") else Found()
    size = extract_size(attrs, title, description) if on("size") else Found()
    weight = extract_weight(attrs, description) if on("weight") else Found()
    inner, outer, every = materials["inner"], materials["outer"], materials["all"]
    return Specs(
        capacity=capacity.value,
        capacity_min_ml=capacity.extra.get("min_ml"),
        capacity_max_ml=capacity.extra.get("max_ml"),
        capacity_source=capacity.source,
        material_inner=inner.value,
        material_outer=outer.value,
        material_all=every.value,
        material_source=inner.source or outer.source or every.source,
        colors=colors.value,
        size=size.value,
        weight=weight.value,
        features=features.value,
        origin=origin.value,
        origin_source=origin.source,
        warranty=warranty.value,
        warranty_source=warranty.source,
        attributes=groups,
    )
