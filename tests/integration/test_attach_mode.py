"""Attach mode: plain Chrome + CDP. A Chrome left over on the profile is cleaned
up (real run 11/09: 'Chrome exited right after opening'), and closing leaves nothing behind."""
from __future__ import annotations

import os
import subprocess
import time

import pytest

from ecommerce.ingestion import browser as B

CHROME = os.environ.get("ECOMMERCE_CHROME_EXECUTABLE")
pytestmark = pytest.mark.skipif(not CHROME or os.name == "nt", reason="needs ECOMMERCE_CHROME_EXECUTABLE (posix)")


def test_leftover_chrome_on_profile_is_replaced_and_nothing_is_left(tmp_path):
    profile = tmp_path / "prof"
    profile.mkdir()
    stray = subprocess.Popen([CHROME, f"--user-data-dir={profile}", "--headless=new", "--no-sandbox",
                              "--remote-debugging-port=0", "about:blank"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    assert stray.poll() is None, 'stray chrome exited'
    assert B.profile_chrome_pids(profile)                 # the stray one is found
    with B.open_context(profile, headless=True, mode="attach") as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("data:text/html,<title>ok</title>")
        assert page.title() == "ok"
        assert page.evaluate("navigator.webdriver") is False
    stray.poll()
    time.sleep(1)
    assert B.profile_chrome_pids(profile) == []           # closed cleanly, nothing holds the profile
    with B.open_context(profile, headless=True, mode="attach") as ctx:   # and it reopens
        assert ctx is not None
