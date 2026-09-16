import pytest

from ecommerce.settings import TimeoutSettings


@pytest.fixture
def fast_timeouts() -> TimeoutSettings:
    """Real runs wait 5-10 s between SKU clicks; the fake sites only need 0.6-1 s
    (their JS answers after ~0.3 s). Passed in like the real config would be."""
    return TimeoutSettings(click_pause_min_ms=600, click_pause_max_ms=1000)
