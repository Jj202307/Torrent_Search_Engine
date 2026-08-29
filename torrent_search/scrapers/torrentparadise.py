"""TorrentParadise.org scraper. DHT meta-search, flexible parsing."""

import httpx
from bs4 import BeautifulSoup

from ..base import BaseScraper, SearchResult, Source
from ..config import (
    SITE_URLS,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    MAX_RESULTS_PER_SOURCE,
)
from ..normalizer import extract_info_hash, parse_size, to_int

SEARCH_URL = f"{SITE_URLS['torrentparadise']}/"


class TorrentParadiseScraper(BaseScraper):
    source = Source.TORRENTPARADISE

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=True,
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
                info_hash = extract_info_hash(href)

                title = a.get_text(" ", strip=True) or a.get("title", "").strip()
                if not title and info_hash:
                    title = info_hash
                if not title:
                    continue

                context = a
                for up in (a.parent, a.find_parent("div"), a.find_parent("li"),
                           a.find_parent("tr"), a.find_parent("table")):
                    if up is not None:
                        context = up
                        break

                context_text = context.get_text(" ", strip=True)
                size_bytes = parse_size(context_text)

                seeders = leechers = 0
                nums = [to_int(n) for n in context_text.replace(",", "").split() if n.isdigit()]
                if len(nums) >= 2:
                    seeders, leechers = nums[-2], nums[-1]
                elif len(nums) == 1:
                    seeders = nums[0]

                results.append(SearchResult(
                    title=title,
                    source=self.source,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    magnet=href,
                    torrent_url=href,
                    info_hash=info_hash,
                ))
            except Exception:
                continue
        return results

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        client = await self._get_client()
        params = {"q": query}
        try:
            resp = await client.get(SEARCH_URL, params=params)
            resp.raise_for_status()
            results = self._parse_html(resp.text)
            if results:
                return results
        except Exception:
            pass

        try:
            resp = await client.get(f"{SEARCH_URL}search/{query}")
            resp.raise_for_status()
            return self._parse_html(resp.text)
        except Exception:
            return []

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(SITE_URLS["torrentparadise"])
            resp.raise_for_status()
            return 200 <= resp.status_code < 400
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
