"""EXT.to scraper. Magnet-only indexer, Cloudflare-protected."""

import logging
import re
from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

from ..base import BaseScraper, SearchResult, Source
from ..config import (
    SITE_URLS,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    MAX_RESULTS_PER_SOURCE,
)
from ..normalizer import parse_size, to_int

logger = logging.getLogger(__name__)

try:
    from ..flaresolverr import (
        solve_url as flaresolverr_solve,
        load_replay_cache,
        save_replay_cache,
        clear_replay_cache,
        replay_get,
    )
except ImportError:
    flaresolverr_solve = None
    load_replay_cache = save_replay_cache = clear_replay_cache = replay_get = None

SEARCH_URL = f"{SITE_URLS['extto']}/"

SORT_MAP = {
    "date": "date",
    "size": "size",
    "seeders": "seeders",
    "name": "name",
}

_BROWSER_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": SITE_URLS["extto"],
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class EXTtoScraper(BaseScraper):
    source = Source.EXTTO

    def __init__(self):
        self._client: AsyncSession | None = None

    async def _get_client(self) -> AsyncSession:
        if self._client is None:
            self._client = AsyncSession(
                impersonate="firefox135",
                timeout=DEFAULT_TIMEOUT,
                headers=_BROWSER_HEADERS,
            )
        return self._client

    def _is_challenge(self, html: str) -> bool:
        """Detect Cloudflare JS-challenge page in response body."""
        markers = (
            "One moment...",
            "challenges.cloudflare.com",
            "Один момент",
        )
        return any(m in html for m in markers)

    async def _fetch_via_flaresolverr(self, query: str) -> list[SearchResult]:
        """Fall back to FlareSolverr when curl_cffi gets blocked."""
        if flaresolverr_solve is None:
            logger.warning("FlareSolverr client not available — import failed")
            return []
        # Site's own search form: <form action="/browse/"><input name="q">
        # (GET /browse/?q=<query>). Plain /?q= returns the generic homepage
        # listing (query ignored — verified via fixture).
        url = f"{SITE_URLS['extto']}/browse/?q={query}"
        try:
            result = await flaresolverr_solve(url, session_id="extto")
            if not result or not result.get("html"):
                logger.warning("FlareSolverr returned no HTML for %s", url)
                return []
            # Persist the clearance so the NEXT search replays it
            # via curl_cffi instead of re-solving through FlareSolverr.
            save_replay_cache(
                "ext.to",
                result.get("cookies") or [],
                result.get("userAgent") or "",
            )
            return self._parse_html(result["html"])
        except Exception:
            logger.warning("FlareSolverr request failed for query '%s'", query)
            return []

    # Browse rows carry NO magnets for guests: the download button is
    # <a class="dwn-btn search-magnet-btn" href="javascript:void(0);"
    # data-id="8696336"> — an auth-gated AJAX endpoint. So rows are parsed
    # metadata-only; magnet stays empty (never fabricated).
    _DETAIL_HREF_RE = re.compile(r"/\S*?-\d+/$")

    def _parse_html(self, html: str) -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        for tr in soup.find_all("tr"):
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
            link = tr.find("a", class_="torrent-title-link")
            if link is None:
                link = tr.find("a", href=self._DETAIL_HREF_RE)
            if link is None or not link.get("href"):
                continue
            try:
                title = link.get_text(" ", strip=True)
                if not title:
                    title = (link.get("data-tooltip") or "").strip()
                if not title:
                    continue

                torrent_url = urljoin(SITE_URLS["extto"], link["href"])

                # Labeled cells: <span class="add-block">Size</span><span>1.35 GB</span>
                size_text = seeds_text = leechs_text = ""
                for td in tr.find_all("td"):
                    label = td.find("span", class_="add-block")
                    if not label:
                        continue
                    name = label.get_text(strip=True).lower()
                    spans = td.find_all("span")
                    if len(spans) < 2:
                        continue
                    value = spans[-1].get_text(" ", strip=True)
                    if name == "size":
                        size_text = value
                    elif name == "seeds":
                        seeds_text = value
                    elif name == "leechs":
                        leechs_text = value

                size_bytes = parse_size(size_text or tr.get_text(" ", strip=True))

                seeders = to_int(seeds_text)
                leechers = to_int(leechs_text)
                if not seeders:
                    # Fallback: trailing integer pair anywhere in the row.
                    row_text = tr.get_text(" ", strip=True)
                    nums = [to_int(n) for n in row_text.replace(",", "").split() if n.isdigit()]
                    if len(nums) >= 2:
                        seeders, leechers = nums[-2], nums[-1]

                results.append(SearchResult(
                    title=title,
                    source=self.source,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    magnet="",
                    torrent_url=torrent_url,
                ))
            except Exception:
                continue
        return results

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        sort = kwargs.get("sort")
        if sort and sort.lower() in SORT_MAP:
            sort = SORT_MAP[sort.lower()]

        params = {"q": query}
        if sort:
            params["sort"] = sort

        client = await self._get_client()

        # Fast path: replay the cached FlareSolverr clearance via curl_cffi.
        if flaresolverr_solve is not None and load_replay_cache("ext.to"):
            hit = await replay_get(
                f"{SITE_URLS['extto']}/browse/?q={query}", "ext.to",
                referer=SITE_URLS["extto"],
            )
            if hit and hit[0] == 200 and not self._is_challenge(hit[1]):
                results = self._parse_html(hit[1])
                if results:
                    logger.info(
                        "EXT.to: replay-cache hit — skipping FlareSolverr solve"
                    )
                    return results
            clear_replay_cache("ext.to")

        # Primary attempt: curl_cffi with all URL variants
        attempts = [
            (SEARCH_URL, params),
            (f"{SEARCH_URL}?q={query}", None),
            (f"{SITE_URLS['extto']}/search/?q={query}", None),
            (f"{SITE_URLS['extto']}/?search={query}", None),
        ]

        for url, p in attempts:
            try:
                resp = await client.get(url, params=p)
                if resp.status_code in (403, 429, 503):
                    logger.warning(
                        "EXT.to returned HTTP %s — Cloudflare challenge",
                        resp.status_code,
                    )
                    return await self._fetch_via_flaresolverr(query)
                resp.raise_for_status()
                if self._is_challenge(resp.text):
                    logger.warning("EXT.to JS-challenge detected — falling back to FlareSolverr")
                    return await self._fetch_via_flaresolverr(query)
                results = self._parse_html(resp.text)
                if results:
                    return results
            except Exception:
                continue

        # All primary attempts failed — final FlareSolverr attempt
        if flaresolverr_solve is not None:
            logger.warning("All curl_cffi attempts failed — trying FlareSolverr")
            return await self._fetch_via_flaresolverr(query)

        return []

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(SITE_URLS["extto"])
            resp.raise_for_status()
            return 200 <= resp.status_code < 400
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
