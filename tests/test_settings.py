"""Configuration is checked by Pydantic when it is loaded: a typo or a wrong
type fails at start-up with the field name, never silently hours into a crawl."""
import pytest
from pydantic import ValidationError

from ecommerce.settings import BUNDLED_CONFIG_DIR, AppConfig, CrawlRequest, TimeoutSettings, load_config, load_domain


def test_bundled_config_files_are_valid():
    cfg = load_config(BUNDLED_CONFIG_DIR)
    assert cfg.shopee.target > 0 and cfg.tiktok.target > 0
    assert cfg.shopee.browser.profile_path.is_absolute()
    assert cfg.app.default_domain == "giu_nhiet"
    assert load_domain(cfg.app.default_domain, BUNDLED_CONFIG_DIR).name == "giu_nhiet"


def test_repo_configs_match_the_bundled_defaults():
    """configs/ at the repo root is what people edit; the package ships a copy so
    an installed wheel works. The two must not drift."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1] / "configs"
    if not repo.is_dir():
        pytest.skip("not running from a checkout")
    for bundled in BUNDLED_CONFIG_DIR.rglob("*.yaml"):
        twin = repo / bundled.relative_to(BUNDLED_CONFIG_DIR)
        assert twin.read_text(encoding="utf-8") == bundled.read_text(encoding="utf-8"), twin


def test_missing_sections_use_defaults():
    cfg = AppConfig.model_validate({})
    assert cfg.shopee.sort_by == "sales" and cfg.timeouts.click_pause_min_ms == 5_000
    assert cfg.tiktok.pacing.delay_min_s == 3 and cfg.tiktok.browser.profile_dir.endswith("tiktok")


@pytest.mark.parametrize("data, where", [
    ({"shopee": {"taget": 200}}, "taget"),                                   # typo -> error, not a silent default
    ({"shopee": {"target": 0}}, "target"),
    ({"shopee": {"sort_by": "popular"}}, "sort_by"),
    ({"tiktok": {"pacing": {"delay_min_s": "ba giây"}}}, "delay_min_s"),
    ({"shopee": {"pacing": {"delay_min_s": 50, "delay_max_s": 10}}}, "delay"),   # min > max
    ({"shopee": {"browser": {"name": "firefox"}}}, "name"),
    ({"app": {"export": {"embedded_images": 99}}}, "embedded_images"),
])
def test_bad_values_are_rejected_with_the_field_name(data, where):
    with pytest.raises(ValidationError) as exc:
        AppConfig.model_validate(data)
    assert where in str(exc.value)


def test_keyword_is_a_runtime_input_not_configuration():
    cfg = AppConfig.model_validate({})
    with pytest.raises(RuntimeError):
        _ = cfg.keyword
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"keyword": "x"})            # no such YAML key any more
    req = CrawlRequest(platform="tiktok", keyword="Bình giữ nhiệt", max_products=50)
    two = cfg.with_request(req)
    assert two.keyword == "Bình giữ nhiệt" and two.platform == "tiktok"
    assert two.tiktok.target == 50 and cfg.tiktok.target == 200   # --max-products overrides, copy only
    assert req.keyword_slug == "binh-giu-nhiet"
    with pytest.raises(ValidationError):
        CrawlRequest(platform="amazon", keyword="x")


def test_domain_profile_is_optional_and_validated(tmp_path):
    assert load_domain(None) is None
    with pytest.raises(FileNotFoundError):
        load_domain("nope", tmp_path)
    (tmp_path / "domains").mkdir()
    (tmp_path / "domains" / "bad.yaml").write_text("filter:\n  keep_nouns: [['(', 'x']]\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_domain("bad", tmp_path)
    (tmp_path / "domains" / "empty.yaml").write_text("description: nothing\n", encoding="utf-8")
    empty = load_domain("empty", tmp_path)
    assert empty.name == "empty" and not empty.filter.keep_nouns and empty.specs.on("capacity")


def test_config_is_frozen_and_updates_make_a_validated_copy():
    cfg = AppConfig.model_validate({})
    with pytest.raises(ValidationError):
        cfg.shopee.target = 5
    two = cfg.with_updates(shopee={"sku_stock": False})
    assert two.shopee.sku_stock is False and cfg.shopee.sku_stock is True
    with pytest.raises(ValidationError):
        cfg.with_updates(shopee={"target": -1})


def test_timeouts_range_check():
    with pytest.raises(ValidationError):
        TimeoutSettings(click_pause_min_ms=10_000, click_pause_max_ms=5_000)
