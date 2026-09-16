"""Lazada session state (login is done by a person once, in a plain browser)."""
from __future__ import annotations


def lazada_login_state(context) -> bool | None:
    """True / False from Lazada's cookies; None if we cannot tell.

    A logged-in Lazada session sets `lzd_uid` / `lzd_sid` (and `_m_h5_tk`);
    guests only carry `lzd_cid` / `t_uid`."""
    try:
        cookies = {c["name"]: c.get("value", "") for c in context.cookies("https://www.lazada.vn")}
    except Exception:
        return None
    if not cookies:
        return False
    if cookies.get("lzd_uid") or cookies.get("lzd_sid"):
        return True
    return False if "lzd_cid" in cookies else None
