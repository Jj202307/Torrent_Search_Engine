"""EXT.to scraper. Magnet-only indexer, Cloudflare-protected."""

import httpx
from bs4 import BeautifulSoup

from ..base import BaseScraper, SearchResult, Source
from ..config import (
    SITE_URLS,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    MAX_RESULTS_PER_SOURCE,
)
from ..normalizer import parse_size, to_int

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
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers=_BROWSER_HEADERS,
                follow_redirects=True,
                http2=True,
            )
        return self._client

    def _parse_html(self, html: str) -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        for a in soup.find_all("a", href=True):
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
            href = a["href"]
            if not href.startswith("magnet:"):
                continue
            try:
                container = a
                parent = a.parent
                if parent is not None:
                    container = parent

                title = a.get_text(" ", strip=True) or a.get("title", "").strip()
                if not title:
                    title = href.split("dn=")[1].split("&")[0] if "dn=" in href else ""

                size_bytes = parse_size(container.get_text(" ", strip=True))

                seeders = leechers = 0
                for sib in [parent, a.find_parent("tr"), a.find_parent("li"),
                            a.find_parent("div"), a.parent]:
                    if sib is None:
                        continue
                    text = sib.get_text(" ", strip=True)
                    nums = [to_int(n) for n in text.replace(",", "").split() if n.isdigit()]
                    if len(nums) >= 2:
                        seeders, leechers = nums[-2], nums[-1]
                        break

                results.append(SearchResult(
                    title=title,
                    source=self.source,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    magnet=href,
                    torrent_url=href,
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
        attempts = [
            (SEARCH_URL, params),
            (f"{SEARCH_URL}?q={query}", None),
            (f"{SITE_URLS['extto']}/search/?q={query}", None),
            (f"{SITE_URLS['extto']}/?search={query}", None),
        ]

        for url, p in attempts:
            try:
                resp = await client.get(url, params=p)
                resp.raise_for_status()
                results = self._parse_html(resp.text)
                if results:
                    return results
            except Exception:
                continue
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
            await self._client.aclose()
            self._client = None
