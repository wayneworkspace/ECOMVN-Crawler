"""Read Lazada pages from inside the real browser tab (same recipe as TikTok).

* Search: `/catalog/?q=...&sort=popularity&page=N&ajax=true` answers JSON when
  requested from a tab that already passed Lazada's checks.
* Product: GET the HTML by XMLHttpRequest and cut `window.__moduleData__ = {...}`
  (and `window.pdpTrackingData`) out of it with a brace-matching scanner --
  no script of the page is executed, only its data is read.

Lazada's anti-bot ("punish" page / slider captcha) answers with HTTP 200 HTML
that has no data. When that happens the tab itself is navigated to the URL so
the person can solve the puzzle, then the request is retried.

Why in the page and not with `requests`: same cookies, TLS/HTTP2 fingerprint
and origin as a person browsing; the login session lives in this profile.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ecommerce.ingestion.browser import human_pause
from ecommerce.platforms.lazada.parse.common import BASE

log = logging.getLogger(__name__)

WALL_MARKERS = ("punish", "captcha", "verify", "slide", "x5secdata", "_____tmd_____", "xác minh", "robot")

_JS = r"""
async ([path, timeoutMs, wantJson]) => {
  const r = await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open('GET', path);
    x.timeout = timeoutMs;
    x.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    x.onload = () => resolve({status: x.status, text: x.responseText, url: x.responseURL});
    x.onerror = () => resolve({status: 0, text: '', url: path, error: 'network'});
    x.ontimeout = () => resolve({status: 0, text: '', url: path, error: 'timeout'});
    x.send();
  });
  const out = {status: r.status, url: r.url, error: r.error || null, size: (r.text || '').length,
               title: null, json: null, module: null, tracking: null, wall: false};
  const text = r.text || '';
  if (!text) return out;
  const low = text.slice(0, 4000).toLowerCase();
  out.wall = /punish|x5secdata|_____tmd_____|captcha|slide to verify|nc_1_n1z/.test(low);
  if (wantJson) {
    try { out.json = JSON.parse(text); return out; } catch (e) { /* HTML: fall through */ }
  }
  const t = text.match(/<title[^>]*>([^<]*)<\/title>/i);
  out.title = t ? t[1].trim() : null;
  // cut `window.NAME = {...}` out of the HTML without running any script
  const cut = (name) => {
    const i = text.indexOf(name);
    if (i < 0) return null;
    let j = text.indexOf('{', i);
    if (j < 0) return null;
    let depth = 0, inStr = false, esc = false, q = '';
    for (let k = j; k < text.length; k++) {
      const c = text[k];
      if (inStr) {
        if (esc) esc = false;
        else if (c === '\\') esc = true;
        else if (c === q) inStr = false;
        continue;
      }
      if (c === '"' || c === "'") { inStr = true; q = c; continue; }
      if (c === '{') depth++;
      else if (c === '}') { depth--; if (depth === 0) {
        try { return JSON.parse(text.slice(j, k + 1)); } catch (e) { return {__parse_error: String(e).slice(0, 200)}; }
      } }
    }
    return null;
  };
  out.module = cut('__moduleData__');
  out.tracking = cut('pdpTrackingData');
  return out;
}
"""


class LazadaWall(Exception):
    """Captcha / punish page instead of the data."""


class PageMissing(Exception):
    """404 or a page without data (product removed)."""


@dataclass
class PageData:
    path: str
    status: int
    json: Any = None
    module: dict | None = None
    tracking: dict | None = None
    title: str | None = None


def is_wall(result: dict) -> bool:
    if result.get("wall"):
        return True
    title = (result.get("title") or "").lower()
    if any(w in title for w in WALL_MARKERS):
        return True
    return result.get("status") in (403, 429)


class Fetcher:
    """One browser tab on lazada.vn used for every request."""

    def __init__(self, context, timeout_ms: int = 60_000, max_walls: int = 3):
        self.context = context
        self.timeout_ms = timeout_ms
        self.max_walls = max_walls
        self.page = None

    def open(self, start_path: str = "/") -> None:
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self._goto(start_path)
        if self._showing_wall():
            self._solve(start_path)

    def _goto(self, path: str) -> None:
        url = path if path.startswith("http") else BASE + path
        self.page.goto(url.replace("&ajax=true", ""), wait_until="domcontentloaded", timeout=self.timeout_ms)
        self.page.wait_for_timeout(2500)

    def _showing_wall(self) -> bool:
        try:
            url = (self.page.url or "").lower()
            title = (self.page.title() or "").lower()
        except Exception:
            return False
        return any(w in url or w in title for w in WALL_MARKERS)

    def _solve(self, path: str) -> None:
        """Show the captcha in the tab and wait for the person."""
        if not self._showing_wall():
            self._goto(path)
        human_pause("Lazada shows a verification (slider captcha / 'punish' page).\n"
                    "Solve it in the tool's browser window until the Lazada page appears, then press Enter.")
        self.page.wait_for_timeout(1500)

    def get(self, path: str, want_json: bool = False) -> PageData:
        """GET a Lazada page. Pauses for captchas; raises PageMissing on 404 / no data."""
        if self.page is None:
            self.open()
        for attempt in range(self.max_walls + 1):
            result = self.page.evaluate(_JS, [path, self.timeout_ms, want_json])
            status = result.get("status") or 0
            if want_json and isinstance(result.get("json"), dict):
                return PageData(path, status, json=result["json"])
            if not want_json and isinstance(result.get("module"), dict) and "__parse_error" not in result["module"]:
                return PageData(path, status, module=result["module"], tracking=result.get("tracking"),
                                title=result.get("title"))
            if status == 404 or "404" in (result.get("title") or ""):
                raise PageMissing(f"404: {path}")
            if status == 0:
                log.warning("Could not load %s (%s), retrying", path, result.get("error"))
                self.page.wait_for_timeout(5000 * (attempt + 1))
                continue
            if is_wall(result):
                if attempt >= self.max_walls:
                    break
                log.warning("Verification at %s (HTTP %s, title=%r)", path, status, result.get("title"))
                self._solve(path)
                continue
            err = (result.get("module") or {}).get("__parse_error") if isinstance(result.get("module"), dict) else None
            raise PageMissing(f"HTTP {status}, no product data (title={result.get('title')!r}"
                              f"{', parse error: ' + err if err else ''}): {path}")
        raise LazadaWall(f"Still blocked after {self.max_walls} captcha rounds: {path}")
