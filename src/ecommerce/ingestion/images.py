"""Download product thumbnails once, cache them, shrink them for Excel.

Images come from the public CDN, not from Shopee's API, so plain HTTP with a
few threads is fine here -- this never touches the logged-in browser session.
Thumbnails are resized BEFORE embedding: 200 products x 3 full-size photos
would make a 100 MB workbook; 110 px JPEGs keep it at a few MB.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
}


_TIKTOK_SIZE = re.compile(r"(crop|resize)-(webp|jpeg|jpg|png|image):\d+:\d+\.(webp|jpeg|jpg|png|image)")


def thumb_source_url(url: str) -> str:
    """Ask the CDN for a small rendition instead of the full photo.

    Shopee: append '_tn'. TikTok (ibyteimg / tiktokcdn): the size is part of
    the image template in the URL, e.g. '~tplv-xxx-crop-webp:1200:1200.webp'
    -> 'resize-jpeg:220:220.jpeg' (JPEG also avoids WebP decoding issues).
    """
    if "susercontent.com/file/" in url and not url.endswith("_tn"):
        return url + "_tn"
    if "~tplv-" in url:
        return _TIKTOK_SIZE.sub("resize-jpeg:220:220.jpeg", url, count=1)
    return url


def headers_for(url: str) -> dict:
    referer = "https://shopee.vn/" if "susercontent.com" in url else "https://shop.tiktok.com/"
    return {**HEADERS, "Referer": referer}


def cache_path(cache_dir: Path, url: str, size_px: int) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return cache_dir / f"{digest}_{size_px}.jpg"


def make_thumbnail(raw: bytes, size_px: int) -> bytes:
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        im.thumbnail((size_px, size_px))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue()


def fetch_thumbnail(url: str, cache_dir: Path, size_px: int, session=None) -> bytes | None:
    path = cache_path(cache_dir, url, size_px)
    if path.exists():
        return path.read_bytes()
    http = session or requests
    for candidate in (thumb_source_url(url), url):
        try:
            resp = http.get(candidate, headers=headers_for(candidate), timeout=20)
            if resp.status_code == 200 and resp.content:
                data = make_thumbnail(resp.content, size_px)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                return data
        except Exception as exc:
            log.debug("Image download failed %s: %s", candidate, exc)
    return None


def fetch_many(urls: list[str], cache_dir: Path, size_px: int, workers: int = 8) -> dict[str, bytes]:
    unique = list(dict.fromkeys(u for u in urls if u))
    results: dict[str, bytes] = {}
    with requests.Session() as session, ThreadPoolExecutor(max_workers=workers) as pool:
        for url, data in zip(unique, pool.map(
                lambda u: fetch_thumbnail(u, cache_dir, size_px, session), unique), strict=False):
            if data:
                results[url] = data
    missing = len(unique) - len(results)
    if missing:
        log.warning("%d/%d images could not be downloaded (picture cell left empty, link kept)", missing, len(unique))
    return results
