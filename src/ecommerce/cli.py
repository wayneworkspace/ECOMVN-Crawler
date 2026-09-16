"""Command line entry point: `ecommerce <command> --platform <name> --keyword "..."`.

    ecommerce init                          copy the bundled configs/ into the current folder
    ecommerce platforms                     list the registered platforms
    ecommerce login --platform shopee       log in ONCE in the tool's own browser profile
    ecommerce probe  --keyword K            try 20 products then export, to check by hand
    ecommerce crawl  --keyword K            NEW run: a snapshot of the top N at this moment
    ecommerce crawl  --keyword K --pass 1   Shopee pass 1: only open product pages (fast, few requests)
    ecommerce crawl  --keyword K --pass 2   Shopee pass 2: come back and click variations for per-SKU stock
    ecommerce resume --keyword K            continue the latest run that was interrupted
    ecommerce export --keyword K            raw JSON -> Excel, no browser
    ecommerce status                        progress of the latest run
    ecommerce inspect SHOPID_ITEMID         key tree of one product's JSON (to map new fields)
    ecommerce check-schema                  do the saved JSON files still have the fields the tool reads?
    ecommerce check-schema --save-baseline  make this (verified good) run the baseline for later checks

Common options
    --platform shopee|tiktok   default: app.yaml default_platform
    --keyword "bình giữ nhiệt" the search keyword (a run-time input, never configuration)
    --domain giu_nhiet         domain profile (product filter + attribute vocabularies);
                               default: app.yaml default_domain; "none" = no profile
    --max-products N           overrides <platform>.target
    --run <id>                 pick one run by its folder name under data/raw/<platform>/
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import shutil
import sys
from pathlib import Path

from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms import get_adapter, platform_names
from ecommerce.settings import (
    BUNDLED_CONFIG_DIR,
    AppConfig,
    CrawlRequest,
    config_dir,
    load_config,
    load_domain,
    project_home,
)

log = logging.getLogger(__name__)


def _setup_console() -> None:
    # Windows consoles default to cp1252/cp437: Vietnamese output would crash.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    # Ctrl+C while Chrome is busy leaves patchright's pending tasks behind; asyncio
    # then prints "Task was destroyed" / TargetClosedError noise. Harmless, hide it.
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# configuration + run selection
# ---------------------------------------------------------------------------
def _platform(args, cfg: AppConfig | None = None) -> str:
    return getattr(args, "platform", None) or (cfg or load_config()).app.default_platform


def _config(args, need_keyword: bool = False) -> AppConfig:
    """app + platform settings, the runtime request and the domain profile."""
    base = load_config()
    platform = _platform(args, base)
    keyword = getattr(args, "keyword", None)
    if not keyword and need_keyword:
        sys.exit("--keyword is required (the keyword is a run-time input, not configuration)")
    domain_name = getattr(args, "domain", None) or base.app.default_domain
    if domain_name and domain_name.lower() == "none":
        domain_name = None
    domain = load_domain(domain_name)
    if not keyword:
        return base.model_copy(update={"domain": domain})
    request = CrawlRequest(platform=platform, keyword=keyword, domain=domain_name,
                           max_products=getattr(args, "max_products", None))
    return base.with_request(request, domain)


def _store(args, cfg: AppConfig, create: bool = False) -> RunStore:
    """Which run a command works on.

    `crawl` always opens a NEW run: every Excel file is a snapshot, prices and
    stock change daily, so mixing two days into one file is wrong. `resume`
    (or `--run <name>`) continues the latest run instead.
    """
    platform = _platform(args, cfg)
    root = cfg.paths.raw
    keyword = cfg.request.keyword if cfg.request else None
    if getattr(args, "run", None):
        return RunStore(platform, args.run, root)
    if getattr(args, "new_run", False):
        _warn_unfinished(platform, root)
        return RunStore.new(platform, root, keyword=keyword, domain=cfg.domain.name if cfg.domain else None,
                            extra={"target": cfg.for_platform(platform).target})
    latest = RunStore.latest(platform, root, keyword=keyword)
    if latest is None:
        if not create:
            sys.exit(f"No {platform} run found under {root}. Run `ecommerce crawl --platform {platform} "
                     f"--keyword ...` first.")
        return RunStore.new(platform, root, keyword=keyword, domain=cfg.domain.name if cfg.domain else None)
    return latest


def _progress(store: RunStore) -> tuple[int, int]:
    """(products saved, candidates) of one run."""
    if not store.candidates_path.exists():
        return 0, 0
    kept = read_json(store.candidates_path).get("kept") or []
    return len(list((store.dir / "items").glob("*.json"))), len(kept)


def _warn_unfinished(platform: str, root: Path) -> None:
    """Opening a new run while the previous one is unfinished is usually a mistake."""
    latest = RunStore.latest(platform, root)
    if latest is None:
        return
    done, total = _progress(latest)
    if total and done < total:
        log.warning("Run %s has only %d/%d products. To continue it instead, stop now and run "
                    "`ecommerce resume --platform %s`.", latest.run_id, done, total, platform)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_init(args) -> None:
    """Copy the bundled configs into <home>/configs so they can be edited."""
    target = project_home() / "configs"
    if target.exists() and not args.force:
        sys.exit(f"{target} already exists (use --force to overwrite).")
    shutil.copytree(BUNDLED_CONFIG_DIR, target, dirs_exist_ok=True)
    print(f"Configuration written to {target}")


def cmd_platforms(args) -> None:
    for name in platform_names():
        info = get_adapter(name).describe()
        print(f"{name:10s} {info['label']:14s} login: {'required' if info['needs_login'] else 'no'}")


LOGIN_TIPS = """
A NORMAL browser window (not driven by the tool) just opened the {label} page.
  * Shopee: prefer "Log in with QR" and scan with the Shopee app. Complete every
    verification step (OTP, captcha) until you see the Shopee home page.
  * TikTok Shop: no account needed; if a "Security Check" / puzzle appears, solve it
    until the product list shows.
  * Then CLOSE that browser window completely (the tool reuses this profile).
"""


def cmd_login(args) -> None:
    """Log in with a plain browser on the tool's profile -- not an automated one.

    Shopee's login form silently ignores the LOG IN click when the browser is
    driven through CDP (the button lights up, nothing happens). A normal Chrome
    started on the same --user-data-dir logs in like any person would; the tool
    then reuses that session. Same executable, same profile, same machine, so
    the session cookies and the fingerprint still match (see decisions #2).
    """
    import subprocess
    import time

    from ecommerce.ingestion.browser import find_chrome, open_context
    cfg = _config(args)
    adapter = get_adapter(_platform(args, cfg))
    browser = adapter.browser(cfg)
    profile = browser.profile_path
    profile.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome(browser.name)
    if chrome is None:
        sys.exit(f"Browser {browser.name} not found. Point ECOMMERCE_CHROME_EXECUTABLE to chrome.exe / msedge.exe.")

    print(LOGIN_TIPS.format(label=adapter.label))
    started = time.monotonic()
    slug = cfg.request.keyword_slug if cfg.request else "shop"
    start_url = adapter.login_url.format(keyword_slug=slug)
    proc = subprocess.Popen([chrome, f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", start_url])
    proc.wait()
    if time.monotonic() - started < 10:
        # Chrome handed the window to an already-running instance of this
        # profile and exited at once; wait for the person instead.
        input("Logged in and CLOSED that browser window? Press Enter...")
    if not adapter.needs_login:
        print(f"{adapter.label} session saved in {profile}")
        return
    with open_context(profile, headless=True, mode=browser.mode, browser_name=browser.name) as ctx:
        from ecommerce.platforms.shopee.extract.session import shopee_login_state
        state = shopee_login_state(ctx)          # only Shopee refuses to crawl as a guest
    if state is False:
        sys.exit("Still NO logged-in session in the profile. Run `ecommerce login` again and make sure "
                 "you reach the home page before closing the window.")
    print("Logged in." if state else "Login state unknown; try crawling anyway.")
    print(f"Session saved in {profile}")


def _apply_pass(cfg: AppConfig, pass_no: int | None) -> AppConfig:
    """Shopee in two passes (Shopee throttles an account that clicks a lot):
    pass 1 = open each product page once (everything on the main sheet),
    pass 2 = come back and click every variation for per-SKU stock (Detail sheet).
    Products saved in pass 1 have no sku_stock yet, so pass 2 reopens exactly those."""
    if not pass_no:
        return cfg
    log.info("Pass %d: %s", pass_no, "product pages only (no variation clicks)" if pass_no == 1
             else "reopen products without per-SKU stock and click every variation")
    return cfg.with_updates(shopee={"sku_stock": pass_no == 2})


PROBE_DISCOVERY_PAGES = {"shopee": ("max_pages", 2), "lazada": ("max_pages", 2), "tiktok": ("max_keyword_pages", 10)}


def _probe_budget(cfg: AppConfig, limit: int) -> AppConfig:
    """`probe` is a quick look: cap the discovery step (search / keyword pages) so
    it does not walk the full budget before opening the first product page, and
    ask only for `limit` products."""
    field, pages = PROBE_DISCOVERY_PAGES.get(cfg.platform, (None, None))
    updates = {"target": min(cfg.for_platform().target, limit)}
    if field and getattr(cfg.for_platform(), field) > pages:
        updates[field] = pages
    log.info("Probe: %s products, discovery capped at %s %s", limit, pages, field or "")
    return cfg.with_updates(**{cfg.platform: updates})


def cmd_crawl(args, limit: int | None = None) -> RunStore:
    from ecommerce.ingestion.browser import open_context

    cfg = _apply_pass(_config(args, need_keyword=True), getattr(args, "pass_no", None))
    if limit is not None:
        cfg = _probe_budget(cfg, limit)
    adapter = get_adapter(cfg.platform)
    store = _store(args, cfg, create=True)
    done, total = _progress(store)
    log.info("Run %s (%s): %s | keyword=%r domain=%s", store.run_id,
             "new" if not total else f"continuing, {done}/{total} products done", store.dir,
             cfg.keyword, cfg.domain.name if cfg.domain else "none")
    browser = adapter.browser(cfg)
    with open_context(browser.profile_path, headless=adapter.headless(cfg), mode=browser.mode,
                      browser_name=browser.name) as ctx:
        adapter.crawl(ctx, store, cfg, limit=limit)
    _print_status(store)
    return store


def cmd_probe(args) -> None:
    store = cmd_crawl(args, limit=args.limit)
    cmd_export(argparse.Namespace(run=store.run_id, no_images=False, platform=_platform(args),
                                  keyword=args.keyword, domain=getattr(args, "domain", None),
                                  max_products=getattr(args, "max_products", None)))


def cmd_export(args) -> None:
    """raw JSON -> Product models (transformation) -> Excel (consumption). No browser."""
    from ecommerce.consumption.excel.excel import load_layout, write_report
    cfg = _config(args)
    store = _store(args, cfg)
    if cfg.request is None:
        # keyword recovered from the run so the domain / file name are right
        keyword = store.keyword
        if keyword:
            cfg = cfg.with_request(CrawlRequest(platform=_platform(args, cfg), keyword=keyword,
                                                domain=cfg.domain.name if cfg.domain else None,
                                                max_products=getattr(args, "max_products", None)), cfg.domain)
    adapter = get_adapter(_platform(args, cfg))
    dataset = adapter.build_dataset(store, cfg)
    prefix = cfg.domain.file_prefix if cfg.domain else (cfg.request.keyword_slug if cfg.request else adapter.name)
    layout_name = (cfg.domain.report.layout if cfg.domain and cfg.domain.report.layout else cfg.export.layout)
    path = write_report(dataset, cfg.export, out_dir=cfg.paths.output, download_images=not args.no_images,
                        prefix=prefix, image_cache=cfg.paths.image_cache, layout=load_layout(layout_name))
    print(f"\nExported: {path}")


def _print_status(store: RunStore) -> None:
    adapter = get_adapter(store.platform)
    model = adapter.candidate_model()
    cands = read_json(store.candidates_path) if store.candidates_path.exists() else {}
    kept = [model.coerce(c) for c in cands.get("kept", [])]
    saved = [c for c in kept if store.has_item(*adapter.item_key(c.key))]
    meta = store.load_meta()
    print(f"\nRun {store.platform}/{store.run_id} | keyword={meta.get('keyword', '?')!r} "
          f"domain={meta.get('domain') or 'none'}: search pages={len(list(store.iter_search_pages()))}, "
          f"candidates={len(kept)}, detail pages crawled={len(saved)}{adapter.status_extra(store, saved)}, "
          f"failures={len(store.load_failures())}")


def cmd_status(args) -> None:
    _print_status(_store(args, _config(args)))


def cmd_check_schema(args) -> None:
    """Compare saved raw JSON with contracts/ (what the tool reads) and the baseline."""
    from ecommerce.contracts import check_run, format_report, save_baseline
    cfg = _config(args)
    store = _store(args, cfg)
    if args.save_baseline:
        for path in save_baseline(store):
            print(f"Baseline saved: {path}")
        print("Commit src/ecommerce/contracts/baselines/ so later runs are compared with this one.")
        return
    reports = check_run(store, drop=cfg.contracts.coverage_drop)
    if not reports:
        sys.exit(f"Run {store.run_id} has no files to check.")
    print(f"Checking run {store.platform}/{store.run_id}")
    print(format_report(reports))
    if any(r.failed for r in reports):
        sys.exit(1)                     # non-zero: usable from a scheduled task / CI


def cmd_inspect(args) -> None:
    cfg = _config(args)
    store = _store(args, cfg)
    a, b = get_adapter(store.platform).item_key(args.key)
    raw = read_json(store.item_path(a, b))

    def tree(obj, prefix="", depth=0):
        if depth > args.depth:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                sample = "" if isinstance(v, (dict, list)) else f" = {json.dumps(v, ensure_ascii=False)[:60]}"
                print(f"{prefix}{k}{sample}")
                tree(v, prefix + "  ", depth + 1)
        elif isinstance(obj, list) and obj:
            print(f"{prefix}[0..{len(obj) - 1}]")
            tree(obj[0], prefix + "  ", depth + 1)

    tree(raw.get(args.part) if args.part else raw)


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------
def _common(p: argparse.ArgumentParser, keyword: bool = True, run: bool = True) -> None:
    p.add_argument("--platform", choices=platform_names(), help="default: app.yaml default_platform")
    if keyword:
        p.add_argument("--keyword", help="search keyword (run-time input)")
        p.add_argument("--domain", help="domain profile in configs/domains/ (default: app.yaml; 'none' = off)")
        p.add_argument("--max-products", type=int, help="overrides <platform>.target")
    if run:
        p.add_argument("--run", help="one specific run (folder name under data/raw/<platform>/)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ecommerce", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="copy the bundled configs into the current folder")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("platforms", help="list registered platforms")
    p.set_defaults(func=cmd_platforms)

    p = sub.add_parser("login", help="log in once in the tool's own browser profile")
    _common(p, run=False)
    p.set_defaults(func=cmd_login)

    def add_crawl(name: str, new_run: bool, help_text: str):
        q = sub.add_parser(name, help=help_text)
        _common(q)
        q.add_argument("--pass", dest="pass_no", type=int, choices=[1, 2],
                       help="Shopee: 1 = product pages only (main sheet), 2 = click variations for per-SKU stock")
        q.set_defaults(func=cmd_crawl, new_run=new_run)
        return q

    # crawl = new snapshot; resume = continue the interrupted run (see _store)
    add_crawl("crawl", True, "NEW run: the latest top N at this moment")
    add_crawl("resume", False, "continue the latest run that was interrupted")

    p = sub.add_parser("probe", help="try a few products then export, to check by hand")
    _common(p)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--new-run", action="store_true", help="open a new run instead of using the latest")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("export", help="raw JSON -> Excel (no browser)")
    _common(p)
    p.add_argument("--no-images", action="store_true", help="do not download / embed pictures (fast check)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("status", help="progress of the latest run")
    _common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("inspect", help="key tree of one product's raw JSON")
    p.add_argument("key", help="e.g. SHOPID_ITEMID (file name under data/raw/<platform>/<run>/items)")
    p.add_argument("--part", choices=["pdp", "ratings", "shop", "candidate", "product_info"], default="pdp")
    p.add_argument("--depth", type=int, default=4)
    _common(p)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("check-schema", help="check saved JSON against the data contracts")
    _common(p)
    p.add_argument("--save-baseline", action="store_true",
                   help="make this (verified good) run the baseline for later comparisons")
    p.set_defaults(func=cmd_check_schema)
    return parser


def main(argv: list[str] | None = None) -> None:
    _setup_console()
    args = build_parser().parse_args(argv)
    from pydantic import ValidationError

    from ecommerce.ingestion.browser import BrowserClosed
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nStopped. Run the same command again to continue where it stopped.")
    except ValidationError as exc:
        sys.exit(f"Invalid configuration under {config_dir()}:\n{exc}")
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    except BrowserClosed:
        print("\nThe browser window was closed, so the tool stopped. Data already captured is kept; "
              "run the same command again to continue.")


if __name__ == "__main__":
    main()
