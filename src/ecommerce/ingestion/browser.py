"""Browser session shared by all platforms.

Design notes (each one is a failure we already paid for, see docs/decisions.md):

* patchright, not playwright + playwright-stealth: stealth's JS patches crash
  Shopee's own inline scripts on current Chrome, so prices never render.
* A dedicated profile, opened by a PLAIN Chrome the tool starts and then attaches
  to (see open_context): log in by hand once, and the session + device
  fingerprint stay together. Exporting cookies into a fresh
  browser makes the fingerprint mismatch and triggers a captcha.
* Data comes from the site's own JSON API responses, never from CSS classes --
  Shopee's class names are hashed and change with every deploy.
* Waiting uses page.wait_for_timeout(), never time.sleep(). The sync API only
  dispatches network events while it is inside a browser call; a time.sleep()
  polling loop makes responses look "late" by however long the loop runs.
"""
from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

# Checked in order. Shopee's "Login Required" page lives at
# /verify/traffic/error?...&is_logged_in=false -- that is a login problem, not
# a traffic problem, and the fix the person needs to hear is different.
BLOCK_MARKERS = {
    "is_logged_in=false": "login_wall",
    "/buyer/login": "login_wall",
    "/verify/captcha": "captcha",
    "/verify/traffic": "traffic_wall",
    "/verify/": "verify",
    "captcha": "captcha",
}

WALL_HELP = {
    "login_wall": ("Shopee says NOT LOGGED IN (the session expired). Logging in inside the window "
                   "driven by the tool usually does NOT work. Press Ctrl+C, run "
                   "`ecommerce login --platform shopee`, then run the crawl command again (it resumes)."),
    "captcha": ("Shopee shows a captcha. Solve it in the Chrome tab.\n"
                "If the captcha box is BLANK / does not load (the refresh button ↻ shows no image): Shopee "
                "refuses to render the captcha in a Chrome driven by the tool. Press Ctrl+C, wait for the tool "
                "to close Chrome, run `ecommerce login --platform shopee` (a PLAIN Chrome), open any product, "
                "solve the captcha there, close Chrome and run `ecommerce crawl` again (it resumes)."),
    "traffic_wall": "Shopee reports unusual traffic. Follow the instructions in the Chrome tab.",
    "verify": "Shopee asks for verification. Follow the instructions in the Chrome tab.",
}


class BrowserClosed(Exception):
    """The person closed the Chrome window: stop cleanly, resume next run."""


class BlockedError(Exception):
    """The site sent us to a captcha / login wall instead of the page."""

    def __init__(self, kind: str, url: str):
        super().__init__(f"{kind} at {url}")
        self.kind = kind
        self.url = url


def wall_help(kind: str) -> str:
    return WALL_HELP.get(kind, f"Shopee blocked the page ({kind}). Handle it in the Chrome tab.")


BROWSER_PATHS = {
    "chrome": [("PROGRAMFILES", r"Google\Chrome\Application\chrome.exe"),
               ("PROGRAMFILES(X86)", r"Google\Chrome\Application\chrome.exe"),
               ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe")],
    "edge": [("PROGRAMFILES(X86)", r"Microsoft\Edge\Application\msedge.exe"),
             ("PROGRAMFILES", r"Microsoft\Edge\Application\msedge.exe")],
}
MAC_PATHS = {"chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"}
LINUX_NAMES = {"chrome": ("google-chrome", "chrome"), "edge": ("microsoft-edge", "msedge")}


def find_chrome(name: str | None = None) -> str | None:
    """The installed browser the crawler drives: Chrome (default) or Edge.

    Both are Chromium, so attach mode works the same; ECOMMERCE_CHROME_EXECUTABLE
    overrides everything (tests)."""
    override = os.environ.get("ECOMMERCE_CHROME_EXECUTABLE")
    if override:
        return override
    import shutil
    name = (name or os.environ.get("ECOMMERCE_BROWSER") or "chrome").lower()
    if name not in BROWSER_PATHS:
        raise ValueError(f"browser.name must be chrome or edge, not {name!r}")
    candidates = [os.path.join(os.environ.get(var, ""), rel) for var, rel in BROWSER_PATHS[name]]
    candidates.append(MAC_PATHS[name])
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    for exe in LINUX_NAMES[name]:
        if shutil.which(exe):
            return shutil.which(exe)
    return None


def context_closed(context) -> bool:
    return bool(getattr(context, "_ecommerce_closed", False))


def is_closed_error(exc: BaseException) -> bool:
    return "has been closed" in str(exc) or "Target closed" in str(exc)


def block_kind(url: str) -> str | None:
    lowered = url.lower()
    for marker, kind in BLOCK_MARKERS.items():
        if marker in lowered:
            return kind
    return None


def _free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ChromeHandedOff(RuntimeError):
    """chrome.exe exited at once: another Chrome already owns this profile."""


def _wait_for_devtools(port: int, proc, timeout_s: float = 30) -> None:
    import json as _json
    import urllib.request
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                _json.loads(resp.read())
                return
        except Exception as exc:
            if proc.poll() is not None:
                raise ChromeHandedOff(
                    "Chrome exited at once: another Chrome is already using this profile") from exc
            time.sleep(0.3)
    raise RuntimeError(f"Chrome did not open the DevTools port {port} within {timeout_s:.0f}s")


def profile_chrome_pids(profile_dir: Path) -> list[int]:
    """chrome.exe processes started with THIS tool profile (never the user's own Chrome)."""
    import subprocess
    needle = str(profile_dir.resolve()).lower()
    pids: list[int] = []
    try:
        if os.name == "nt":
            import base64
            script = ("Get-CimInstance Win32_Process -Filter \"name='chrome.exe' or name='msedge.exe'\" | "
                      "ForEach-Object { '{0}{1}{2}' -f $_.ProcessId, [char]9, $_.CommandLine }")
            # -EncodedCommand: no quoting rules to get wrong between Python and PowerShell
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                 capture_output=True, text=True, timeout=30,
                                 encoding="utf-8", errors="replace").stdout
        else:
            out = subprocess.run(["ps", "-ww", "-eo", "pid=,args="], capture_output=True, text=True, timeout=10).stdout
            out = "\n".join(line.strip().replace(" ", "\t", 1) for line in out.splitlines())
    except Exception as exc:
        log.warning("Could not list Chrome processes: %s", exc)
        return pids
    for line in out.splitlines():
        pid, _, cmd = line.partition("\t")
        cmd = cmd.lower().replace('"', "")
        if f"--user-data-dir={needle}" in cmd and pid.strip().isdigit():
            pids.append(int(pid))
    return pids


def kill_pids(pids: list[int]) -> None:
    import signal
    import subprocess
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def _start_chrome(chrome: str, profile_dir: Path, headless: bool, sandbox: bool):
    import subprocess
    port = _free_port()
    args = [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
            "--no-first-run", "--no-default-browser-check"]
    if headless:
        args.append("--headless=new")
    if not sandbox:
        args.append("--no-sandbox")
    args.append("about:blank")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for_devtools(port, proc)
    except Exception:
        proc.kill()
        raise
    return proc, port


def _shutdown_chrome(browser, proc) -> None:
    """Close Chrome the way the X button does (cookies and the captcha pass are
    flushed to disk), then make sure nothing of it is left holding the profile."""
    try:
        if browser is not None and browser.is_connected():
            session = browser.new_browser_cdp_session()
            session.send("Browser.close")
    except Exception:
        pass
    try:
        proc.wait(timeout=15)
    except Exception:
        kill_pids([proc.pid])


@contextmanager
def open_context(profile_dir: Path, headless: bool = False, mode: str | None = None,
                 browser_name: str | None = None) -> Iterator:
    """One persistent Chrome context for the whole batch.

    Opened once, not per product: the profile directory is locked while in use
    and re-opening it repeatedly is how lock errors and captchas start.

    mode="attach" (default): start a PLAIN Chrome ourselves -- no automation
        flags, no "unsupported command-line flag" bar -- and only attach to it
        over the DevTools port. Measured 11/09: in a Chrome *launched* by
        patchright both Shopee's and TikTok's captcha widgets stay blank (they
        refuse to render for an automation-launched browser); a person can only
        solve them in a browser started normally.
    mode="launch": patchright's launch_persistent_context (the old way; tests).
    """
    from patchright.sync_api import sync_playwright  # heavy import, crawler-only

    profile_dir.mkdir(parents=True, exist_ok=True)
    mode = (mode or os.environ.get("ECOMMERCE_BROWSER_MODE") or "attach").lower()
    # Real installed Chrome by default. ECOMMERCE_CHROME_EXECUTABLE points to
    # another binary (used by the integration tests on CI / Linux).
    executable = os.environ.get("ECOMMERCE_CHROME_EXECUTABLE")
    # The sandbox works on Windows/macOS; Linux containers running as root need it off.
    sandbox = os.name == "nt" or os.environ.get("ECOMMERCE_SANDBOX") == "1"
    with sync_playwright() as pw:
        proc = browser = None
        if mode == "attach":
            chrome = find_chrome(browser_name)
            if chrome is None:
                raise RuntimeError(f"Browser {browser_name or 'chrome'} not found. "
                                   "Point ECOMMERCE_CHROME_EXECUTABLE to chrome.exe / msedge.exe.")
            try:
                proc, port = _start_chrome(chrome, profile_dir, headless, sandbox)
            except ChromeHandedOff as handoff:
                # A Chrome from an earlier run (or the `login` window) still owns
                # the profile. Only processes started with THIS profile are closed.
                leftovers = profile_chrome_pids(profile_dir)
                if not leftovers:
                    raise RuntimeError(
                        "Chrome exited at once: another Chrome window is using the tool's OWN profile "
                        f"({profile_dir}). Close that window (e.g. the one from `login`) and run again.") from handoff
                log.warning("Closing %d leftover Chrome process(es) of profile %s, then reopening",
                            len(leftovers), profile_dir.name)
                kill_pids(leftovers)
                time.sleep(3)
                proc, port = _start_chrome(chrome, profile_dir, headless, sandbox)
            try:
                browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            except Exception:
                kill_pids([proc.pid])
                raise
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            # Closing the Chrome window = the browser disconnects.
            browser.on("disconnected", lambda *_: setattr(context, "_ecommerce_closed", True))
        else:
            channel = "msedge" if (browser_name or "").lower() == "edge" else "chrome"
            browser_choice = {"executable_path": executable} if executable else {"channel": channel}
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                **browser_choice,
                headless=headless,
                chromium_sandbox=sandbox,
                # patchright's recommended stealth setup: real Chrome, headful,
                # no_viewport, and NO custom user agent / locale / headers.
                no_viewport=True,
            )
        # Remember when the person closes the window, so the crawl stops with a
        # clear message instead of recording every remaining product as failed.
        context.on("close", lambda *_: setattr(context, "_ecommerce_closed", True))
        try:
            yield context
        finally:
            if proc is not None:
                _shutdown_chrome(browser, proc)
            else:
                try:
                    context.close()
                except Exception as exc:  # closing must never mask the real error
                    log.warning("Could not close browser: %s", exc)


class ResponseTap:
    """Remember every response whose URL contains one of `fragments`.

    The handler only stores the Response object; bodies are read later from the
    main flow. Reading bodies inside an event handler is where sync-API
    deadlocks come from.
    """

    def __init__(self, page, fragments: tuple[str, ...]):
        self.page = page
        self.fragments = fragments
        self.hits: list = []
        page.on("response", self._on_response)

    def _on_response(self, response) -> None:
        url = response.url
        if any(f in url for f in self.fragments):
            self.hits.append(response)

    def matching(self, fragment: str, predicate: Callable[[str], bool] | None = None) -> list:
        return [r for r in self.hits
                if fragment in r.url and (predicate is None or predicate(r.url))]

    def wait_for(self, fragment: str, timeout_ms: int,
                 predicate: Callable[[str], bool] | None = None,
                 poll_ms: int = 400):
        """Wait until a matching response arrives. Raise BlockedError on a wall.

        Checks the page URL on every tick, so a redirect to a captcha is noticed
        within a second instead of after the whole timeout.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            # Wall check FIRST: Shopee answers the API and then redirects to the
            # login wall in the same breath; the answer is useless in that case.
            kind = block_kind(self.page.url)
            if kind:
                raise BlockedError(kind, self.page.url)
            found = self.matching(fragment, predicate)
            if found:
                # earliest match = the request the navigation itself made;
                # later ones come from widgets (related items, ads carousels).
                return found[0]
            if time.monotonic() >= deadline:
                return None
            self.page.wait_for_timeout(poll_ms)


def read_json_body(response) -> dict | None:
    try:
        body = response.json()
    except Exception as exc:
        log.warning("Response is not JSON (%s): %s", response.url[:120], exc)
        return None
    return body if isinstance(body, dict) else None


def human_pause(message: str) -> None:
    """Hand control to the person at the keyboard (captcha, expired login)."""
    print("\n" + "=" * 70)
    print(message)
    print("When done in the Chrome window, come back here and press Enter to continue.")
    print("(Ctrl+C to stop; the next run continues from where it stopped.)")
    print("=" * 70)
    input()


def jitter_sleep(page, min_s: float, max_s: float, reason: str = "") -> None:
    seconds = random.uniform(min_s, max_s)
    if reason:
        log.info("Pausing %.1fs %s", seconds, reason)
    page.wait_for_timeout(int(seconds * 1000))


def human_scroll(page, steps: int, step_px: int = 900, pause_ms: int = 500) -> None:
    """Scroll like a reader so lazy sections (ratings, shop block) load."""
    for _ in range(steps):
        page.mouse.wheel(0, step_px + random.randint(-150, 150))
        page.wait_for_timeout(pause_ms + random.randint(0, 300))


def save_debug(page, debug_dir: Path, stem: str) -> None:
    """Screenshot + HTML of a failure: tells a captcha from a login wall later."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    try:
        # page.content() takes no timeout argument in the Python API.
        (debug_dir / f"{stem}_{stamp}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(debug_dir / f"{stem}_{stamp}.png"), timeout=10_000)
    except Exception as exc:
        log.warning("Could not save debug evidence: %s", exc)
