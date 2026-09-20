"""End-to-end health probe for the rutracker.org Cloudflare pipeline.

Cloudflare hardened rutracker.org in Jul 2026: every direct HTTP client
— curl_cffi's browser impersonation included — is handed a managed
challenge (HTTP 403 / "Один момент…") on the raw path. This is not an
egress-IP problem: from the same VPN IP, the raw path 403s while the
FlareSolverr path passes, so the differentiator is the client
fingerprint, not the exit node. The sanctioned solve path is the
FlareSolverr sidecar: it clears the challenge in a real Chrome, while
the bb_* login cookies harvested from the user's Firefox are injected
into its session so tracker.php serves authenticated search rows.

The probe verifies that chain, layer by layer, in the order production
searches depend on it:

    1. cookie harvest  — Firefox/Opera profiles must yield bb_session
    2. VPN egress      — ipinfo.io, informational only
    3. FlareSolverr    — the docker sidecar must answer on its API
    4. end-to-end      — the same FS fetch the scraper uses must return
                         parsed tracker.php rows for ?nm=ubuntu

The raw curl_cffi direct request is demoted to an informational line:
a 403 there is the expected steady state and never affects the exit
code.

Exit codes: 0 = end-to-end OK; 1 = a layer is broken (named, with its
fix); 2 = unknown source.
"""
import asyncio
import sys

import httpx
from curl_cffi.requests import AsyncSession

from . import flaresolverr as fs
from .scrapers import rutracker as rt


async def _fs_healthy() -> bool:
    """True when the FlareSolverr sidecar answers on its API endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                fs.FLARESOLVERR_URL,
                json={"cmd": "sessions.list", "maxTimeout": 10000},
            )
            return r.status_code == 200
    except Exception:
        return False


async def _probe() -> int:
    # Layer 1: the login session. cf_clearance is optional here — the
    # FlareSolverr path deliberately excludes it (UA-bound to Firefox
    # while FS runs Chrome), so only bb_session is load-bearing.
    cookies = rt._harvest_firefox_cookies()
    if not cookies.get("bb_session"):
        print(
            "harvested session: MISSING bb_session — "
            "log into rutracker.org in Firefox, then re-run --probe"
        )
        return 1
    cf = (
        "present"
        if cookies.get("cf_clearance")
        else "absent (fine — the FS path does not use it)"
    )
    print(f"harvested session: OK (bb_session; cf_clearance {cf})")

    # Layer 2: egress, informational.
    async with AsyncSession(
        impersonate="firefox135",
        timeout=30,
        headers={"User-Agent": rt.FIREFOX_UA},
    ) as s:
        try:
            j = (await s.get("https://ipinfo.io/json")).json()
            print(
                f"real egress    : {j.get('ip')} | "
                f"{j.get('city')}, {j.get('country')} | {j.get('org')}"
            )
        except Exception:
            print("real egress    : unavailable (informational only)")

        # Informational: the raw direct path is expected to be challenged.
        r = await s.get(rt.SEARCH_URL + "?nm=ubuntu", cookies=cookies)
        if "Just a moment" in r.text or r.status_code in (403, 429, 503):
            print(
                f"direct path    : CHALLENGED (HTTP {r.status_code}) — "
                "expected; FlareSolverr handles this"
            )
        else:
            print("direct path    : PASS (no challenge)")

    # Layer 3: the solve sidecar.
    if not await _fs_healthy():
        print(
            f"FlareSolverr not reachable at {fs.FLARESOLVERR_URL} — "
            "start it: docker start flaresolverr"
        )
        return 1
    print(f"FlareSolverr   : OK at {fs.FLARESOLVERR_URL}")

    # Layer 4: the real verdict — the same FS fetch the scraper's
    # search() fallback uses (session 'rutracker', bb_* cookies only).
    scraper = rt.RuTrackerScraper()
    try:
        html = await scraper._fetch_via_flaresolverr("ubuntu", {})
        challenge = scraper._is_challenge(html)
    finally:
        await scraper.close()
    rows = html.count("viewtopic.php?t=") if html else 0
    if rows and not challenge:
        print(f"verdict        : PASS — {rows} result rows (via FlareSolverr)")
        return 0

    print("verdict        : FAIL — FS solve did not yield results")
    if html and challenge:
        print(
            "broken layer   : FlareSolverr solve returned a challenge page"
            " — inspect: docker logs flaresolverr"
        )
    elif not html:
        print(
            "broken layer   : FlareSolverr request failed"
            " — inspect: docker logs flaresolverr"
        )
    else:
        print(
            "broken layer   : login cookies stale — log into rutracker.org"
            " in Firefox, then re-run --probe"
            " (if it persists: docker logs flaresolverr)"
        )
    return 1


def run_probe(source: str = "rutracker") -> int:
    """Verify the rutracker chain: Firefox cookies → FlareSolverr → rows.

    0 = end-to-end OK, 1 = a named layer is broken, 2 = unknown source.
    """
    if source != "rutracker":
        print(f"no probe implemented for source '{source}'", file=sys.stderr)
        return 2
    return asyncio.run(_probe())
