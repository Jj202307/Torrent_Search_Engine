"""FlareSolverr HTTP client.

Thin async wrapper around the FlareSolverr API (request.get) so the
rutracker scraper can fall back to JS-challenge solving when curl_cffi
gets Cloudflare'd.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

import httpx
from curl_cffi.requests import AsyncSession

from .config import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")
_DEFAULT_TIMEOUT = 300  # seconds — Cloudflare challenges can take a while

# Persistent replay cache: solved CF clearances stored per-host so repeat
# requests skip the 30-60s FlareSolverr solve and replay the clearance
# via curl_cffi (~1-2s). Failure-driven invalidation only — a replay
# that comes back challenged/!200 clears the entry and triggers a fresh
# solve on the next call.
_CACHE_DIR = Path.home() / ".cache" / "torrent_search"
_REPLAY_IMPERSONATE = "chrome136"  # must match the solver's Chrome family (cf. _fs_replay_bytes)


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


def _replay_cache_path(host: str) -> Path:
    return _CACHE_DIR / f"fs_replay_{host}.json"


def load_replay_cache(host: str) -> dict | None:
    """Load the persisted clearance for ``host``.

    Returns ``{"cookies": list[dict], "user_agent": str}`` or None when
    absent/corrupt/incomplete (any error → None).
    """
    try:
        with open(_replay_cache_path(host), "r", encoding="utf-8") as fh:
            entry = json.load(fh)
        if not entry.get("cookies") or not entry.get("user_agent"):
            return None
        return entry
    except Exception:
        return None


def save_replay_cache(host: str, cookies: list[dict], user_agent: str) -> None:
    """Atomically persist the clearance (cookies + UA) for ``host``.

    Skips when there are no cookies (an entry without them can never
    replay). Atomic: temp file in the same dir, then os.replace.
    """
    if not cookies or not user_agent:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_CACHE_DIR, prefix=".fs_replay_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"cookies": cookies, "user_agent": user_agent}, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _replay_cache_path(host))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        logger.debug("save_replay_cache(%s) failed", host, exc_info=True)


def clear_replay_cache(host: str) -> None:
    """Drop the cached clearance for ``host`` (swallow all errors)."""
    try:
        _replay_cache_path(host).unlink(missing_ok=True)
    except Exception:
        pass


async def _replay_fetch(
    url: str, host: str, referer: str | None = None
) -> tuple[int, bytes] | None:
    """One GET through the cached clearance.

    None when there is no cache entry for ``host``; otherwise a single
    curl_cffi GET (Chrome-family impersonation + cached UA/cookies) →
    ``(status, raw bytes)``; any request exception → ``(0, b"")``.
    """
    entry = load_replay_cache(host)
    if entry is None:
        return None
    headers: dict[str, str] = {"User-Agent": entry["user_agent"]}
    if referer:
        headers["Referer"] = referer
    s = AsyncSession(
        impersonate=_REPLAY_IMPERSONATE,
        timeout=DEFAULT_TIMEOUT,
        headers=headers,
        cookies={
            c["name"]: c["value"] for c in entry["cookies"] if c.get("name")
        },
    )
    try:
        resp = await s.get(url)
        return resp.status_code, resp.content
    except Exception:
        return 0, b""
    finally:
        await s.close()


async def replay_get(
    url: str, host: str, referer: str | None = None
) -> tuple[int, str] | None:
    """Text variant of :func:`_replay_fetch` (utf-8, errors replaced)."""
    got = await _replay_fetch(url, host, referer=referer)
    if got is None:
        return None
    return got[0], got[1].decode("utf-8", errors="replace")


async def replay_get_bytes(
    url: str, host: str, referer: str | None = None
) -> tuple[int, bytes] | None:
    """Bytes variant of :func:`_replay_fetch` (binaries, non-utf-8 sites)."""
    return await _replay_fetch(url, host, referer=referer)


async def close():
    """No-op: FlareSolverr is a stateless HTTP sidecar."""
    pass
