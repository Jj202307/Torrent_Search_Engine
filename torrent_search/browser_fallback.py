"""Real-browser fallback for Cloudflare-managed-challenge endpoints.

rutracker.org enabled "newest Cloudflare protections" on 2026-07-29
(dated: qBittorrent-RuTracker-plugin deprecation, Jackett#16975,
elementum-burst#501). Every non-browser TLS fingerprint gets a managed
JS challenge on /forum/tracker.php and dl.php; cookies harvested from a
real browser do NOT transfer (verified locally + burst#501). The only
route that works — converged on by jacred, burst's FlareSolverr fork
and rutracker-cf-proxy — is fetching guarded pages THROUGH a real
browser engine. That is this module.

Engine is selectable via BROWSER_FALLBACK_ENGINE (playwright|patchright|
camoufox, default playwright) pending the engine-matrix verdict; plain
playwright Firefox is known-detected on rutracker as of 2026-09-20.

Optional deps:  uv pip install "torrent-search[playwright]"
                playwright install firefox   (or the chosen engine's browser)
Kill switch:    RUTRACKER_BROWSER_FALLBACK=0 (checked by callers)
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# rutracker serves the challenge page localized — match EN + RU, and
# fall back to a content probe (challenge iframe script) since titles vary.
CHALLENGE_MARKERS = (
    "just a moment",
    "один момент",
    "проверка браузера",
    "checking your browser",
    "attention required",
)
CHALLENGE_WAIT_S = float(os.environ.get("BROWSER_FALLBACK_CHALLENGE_WAIT", "25"))
NAV_TIMEOUT_MS = int(float(os.environ.get("BROWSER_FALLBACK_TIMEOUT", "45")) * 1000)
ENGINE = os.environ.get("BROWSER_FALLBACK_ENGINE", "playwright")


@asynccontextmanager
async def _browser():
    """Yield a running fallback browser (context-managed lifecycle)."""
    if ENGINE == "patchright":
        from patchright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                yield browser
            finally:
                await browser.close()
    elif ENGINE == "camoufox":
        from camoufox.async_api import AsyncCamoufox

        async with AsyncCamoufox(headless=True) as browser:
            yield browser
    else:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.firefox.launch(headless=True)
            try:
                yield browser
            finally:
                await browser.close()


def _session_cookies_for(cookies: dict[str, str] | None, url: str) -> list[dict]:
    """Harvested cookies as Playwright cookie objects.

    cf_* cookies are dropped on purpose: they are bound to the
    fingerprint that earned them, and the fallback browser must mint
    its own clearance through the challenge.
    """
    host = urlsplit(url).netloc.split(":")[0]
    return [
        {"name": name, "value": value, "url": f"https://{host}/"}
        for name, value in (cookies or {}).items()
        if not name.startswith("cf_")
    ]


async def _is_challenged(page) -> bool:
    """Title markers (EN/RU) plus a content probe for the CF iframe."""
    title = (await page.title()).lower()
    if any(marker in title for marker in CHALLENGE_MARKERS):
        return True
    return "challenges.cloudflare.com" in await page.content()


async def _make_page(browser, url: str, cookies: dict[str, str] | None, downloads: bool = False):
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="ru-RU",
        accept_downloads=downloads,
    )
    if cookies:
        await context.add_cookies(_session_cookies_for(cookies, url))
    page = await context.new_page()
    page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    return page


async def _wait_out_challenge(page) -> None:
    """A managed challenge auto-solves in a real engine; wait it out."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CHALLENGE_WAIT_S
    while loop.time() < deadline:
        if not await _is_challenged(page):
            return
        await page.wait_for_timeout(500)
    raise RuntimeError(
        f"Cloudflare challenge did not clear within {CHALLENGE_WAIT_S:.0f}s"
    )


async def fetch_html(
    url: str,
    cookies: dict[str, str] | None = None,
    wait_selector: str | None = None,
) -> str:
    """Load ``url`` in the fallback browser, survive the CF challenge, return HTML.

    Raises RuntimeError if the challenge does not clear in time.
    """
    logger.info("browser fallback [%s]: loading %s", ENGINE, url)
    async with _browser() as browser:
        page = await _make_page(browser, url, cookies)
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await _wait_out_challenge(page)
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=NAV_TIMEOUT_MS)
            html = await page.content()
            logger.info("browser fallback: got %d bytes from %s", len(html), url)
            return html
        finally:
            await browser.close()


async def fetch_bytes(
    url: str,
    cookies: dict[str, str] | None = None,
) -> bytes:
    """Fetch a binary served via content-disposition (rutracker dl.php).

    Navigates the page to ``url`` so the request rides the browser's
    full fingerprint; captures the download event and returns the bytes.
    Falls back to an HTML fetch when no download fires (error pages).
    Returns b"" on failure.
    """
    logger.info("browser fallback [%s]: downloading %s", ENGINE, url)
    async with _browser() as browser:
        page = await _make_page(browser, url, cookies, downloads=True)
        try:
            try:
                async with page.expect_download(timeout=NAV_TIMEOUT_MS) as dl:
                    await page.goto(url)
                download = await dl.value
                path = await download.path()
                with open(path, "rb") as fh:
                    data = fh.read()
                logger.info("browser fallback: downloaded %d bytes", len(data))
                return data
            except Exception:
                # dl.php may have answered with an HTML page (session
                # expired, challenge interstitial) — surface that body.
                html = await page.content()
                logger.warning(
                    "browser fallback: no download from %s (body head: %r)",
                    url, html[:200],
                )
                return b""
        finally:
            await browser.close()
