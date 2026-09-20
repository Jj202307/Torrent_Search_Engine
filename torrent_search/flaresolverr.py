"""FlareSolverr HTTP client.

Thin async wrapper around the FlareSolverr API (request.get) so the
rutracker scraper can fall back to JS-challenge solving when curl_cffi
gets Cloudflare'd.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")
_DEFAULT_TIMEOUT = 300  # seconds — Cloudflare challenges can take a while


async def solve_url(
    url: str,
    session_id: str = "",
    cookies: list[dict] | None = None,
    return_only_cookies: bool = False,
) -> dict | None:
    """Send a ``request.get`` to FlareSolverr and return parsed result.

    ``cookies`` is a list of ``{name, value, domain, path, ...}`` dicts
    handed to FlareSolverr verbatim (it feeds each to driver.add_cookie).

    ``return_only_cookies`` sets the API's ``returnOnlyCookies`` flag:
    response HTML is dropped (cookies only) — faster, for callers that
    only need the cleared session (cf_clearance et al).

    Returns
    -------
    dict  with keys ``html``, ``userAgent``, ``cf_clearance``, ``url``,
          ``cookies`` on success, or ``None`` on any failure. With
          ``return_only_cookies`` the ``html`` value is "".
    """
    payload: dict = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 300000,  # 300 s
    }
    if session_id:
        payload["session"] = session_id
    if cookies:
        payload["cookies"] = cookies
    if return_only_cookies:
        payload["returnOnlyCookies"] = True

    async with httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT,
        follow_redirects=False,
    ) as client:
        try:
            r = await client.post(FLARESOLVERR_URL, json=payload)
            r.raise_for_status()
        except Exception:
            logger.warning("FlareSolverr request.get failed for %s", url)
            return None

        body = r.json()
        if body.get("solution"):
            sol = body["solution"]
            resp = sol.get("response", "")
            cookies_list = sol.get("cookies", [])
            cf_clearance = next(
                (c["value"] for c in cookies_list if c.get("name") == "cf_clearance"),
                "",
            )
            return {
                "html": resp,
                "userAgent": sol.get("userAgent", ""),
                "cf_clearance": cf_clearance,
                "url": sol.get("url", url),
                "cookies": cookies_list,
            }
    return None


async def close():
    """No-op: FlareSolverr is a stateless HTTP sidecar."""
    pass
