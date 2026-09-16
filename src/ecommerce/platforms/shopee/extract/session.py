"""Shopee session state (login is done by a person once, in a plain browser)."""
from __future__ import annotations


def shopee_login_state(context) -> bool | None:
    """True / False from Shopee's session cookies; None if we cannot tell.

    SPC_U holds the user id once logged in ('-' for guests); SPC_ST / SPC_EC
    are session tokens only set for a logged-in account.
    """
    try:
        cookies = {c["name"]: c.get("value", "") for c in context.cookies("https://shopee.vn")}
    except Exception:
        return None
    if not cookies:
        return False
    if cookies.get("SPC_U", "").isdigit() or cookies.get("SPC_ST") or cookies.get("SPC_EC"):
        return True
    return False if "SPC_U" in cookies else None
