"""Read TikTok Shop pages from inside the real browser tab.

Every TikTok Shop web page carries its data as JSON in the server-rendered HTML
(<script id="__MODERN_ROUTER_DATA__">). So instead of navigating the tab to
each product (images, videos, trackers: ~5 MB and many requests per page) the
tool asks the already-open, already-verified tab to GET the HTML with an
XMLHttpRequest and hands back only that JSON.

Why in the page and not with `requests`:
    * same cookies, same TLS / HTTP2 fingerprint, same origin as a person
      browsing -- TikTok's anti-bot checks all of those;
    * the captcha pass-cookie lives in this browser profile.
Why XMLHttpRequest and not fetch(): TikTok's security SDK wraps window.fetch
on product pages and breaks `response.text()` for HTML (measured 11/09).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ecommerce.ingestion.browser import human_pause
from ecommerce.platforms.tiktok.parse.common import BASE

log = logging.getLogger(__name__)

WALL_TITLES = ("security check", "verify", "captcha", "xác minh")

_JS = """
async ([path, timeoutMs]) => {
  const r = await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open('GET', path);
    x.timeout = timeoutMs;
    x.onload = () => resolve({status: x.status, text: x.responseText, url: x.responseURL});
    x.onerror = () => resolve({status: 0, text: '', url: path, error: 'network'});
    x.ontimeout = () => resolve({status: 0, text: '', url: path, error: 'timeout'});
    x.send();
  });
  const out = {status: r.status, url: r.url, error: r.error || null, size: r.text.length,
               title: null, route: null, components: null};
  if (!r.text) return out;
  const doc = new DOMParser().parseFromString(r.text, 'text/html');
  out.title = doc.title;
  const s = doc.getElementById('__MODERN_ROUTER_DATA__');
  if (!s) return out;
  try {
    const d = JSON.parse(s.textContent);
    const loader = d.loaderData || {};
    out.route = Object.keys(loader).find(k => k !== 'layout') || null;
    const pg = loader[out.route] || {};
    out.components = (pg.page_config || {}).components_map || null;
  } catch (e) { out.error = 'bad-json'; }
  return out;
}
"""


class TikTokWall(Exception):
    """Captcha / security check instead of the page."""


class PageMissing(Exception):
    """404 or a page without data (product removed, keyword page gone)."""


@dataclass
class PageData:
    path: str
    status: int
    route: str | None
    components: list


def is_wall(result: dict) -> bool:
    title = (result.get("title") or "").lower()
    if any(w in title for w in WALL_TITLES):
        return True
    return result.get("status") in (403, 429) or (
        result.get("status") == 200 and result.get("components") is None and "404" not in title)


class Fetcher:
    """One browser tab on shop.tiktok.com used for every request."""

    def __init__(self, context, timeout_ms: int = 60_000, max_walls: int = 3):
        self.context = context
        self.timeout_ms = timeout_ms
        self.max_walls = max_walls
        self.page = None

    def open(self, start_path: str = "/vn") -> None:
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self._goto(start_path)
        if self._showing_wall():
            self._solve(start_path)

    def _goto(self, path: str) -> None:
        self.page.goto(BASE.rsplit("/vn", 1)[0] + path, wait_until="domcontentloaded",
                       timeout=self.timeout_ms)
        self.page.wait_for_timeout(2500)

    def _showing_wall(self) -> bool:
        try:
            title = (self.page.title() or "").lower()
        except Exception:
            return False
        return any(w in title for w in WALL_TITLES)

    def _solve(self, path: str) -> None:
        """Show the captcha in the tab and wait for the person."""
        if not self._showing_wall():
            self._goto(path)
        human_pause("TikTok shows a security check (slide puzzle / captcha).\n"
                    "Solve it in the tool's Chrome window until the TikTok Shop page appears.")
        self.page.wait_for_timeout(1500)

    def get(self, path: str) -> PageData:
        """GET a TikTok Shop page, return its components. Pauses for captchas."""
        if self.page is None:
            self.open()
        for attempt in range(self.max_walls + 1):
            result = self.page.evaluate(_JS, [path, self.timeout_ms])
            status = result.get("status") or 0
            if result.get("components") is not None:
                return PageData(path, status, result.get("route"), result["components"])
            if status == 404 or "404" in (result.get("title") or ""):
                raise PageMissing(f"404: {path}")
            if status == 0:
                log.warning("Could not load %s (%s), retrying", path, result.get("error"))
                self.page.wait_for_timeout(5000 * (attempt + 1))
                continue
            if is_wall(result):
                if attempt >= self.max_walls:
                    break
                log.warning("Security check at %s (HTTP %s, title=%r)", path, status, result.get("title"))
                self._solve(path)
                continue
            raise PageMissing(f"HTTP {status}, không có dữ liệu: {path}")
        raise TikTokWall(f"Still blocked after {self.max_walls} captcha rounds: {path}")
