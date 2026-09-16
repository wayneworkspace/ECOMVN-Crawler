"""Shared fixtures (see helpers.py for the configuration helpers)."""
import json

import pytest

from helpers import BUNDLED_CONFIG_DIR, FIXTURES, PROFILE, load_config, make_cfg


@pytest.fixture
def load():
    def _load(name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def profile():
    return PROFILE


@pytest.fixture
def cfg():
    return make_cfg()


@pytest.fixture
def bundled_config():
    return load_config(BUNDLED_CONFIG_DIR)
