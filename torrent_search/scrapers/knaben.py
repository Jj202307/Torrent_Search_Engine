"""Knaben.org multi-tracker meta-search scraper (server-rendered HTML)."""

import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size, to_int

# info_hash lives in the magnet URI as urn:btih:<hex>
_INFO_HASH_RE = re.compile(r"urn:btih:([0-9A-Fa-f]+)")


class KnabenScraper(BaseScraper):
    source = Source.KNABEN

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    def _build_url(self, query: str) -> str:
        # PATH route only: /search/<query>. The query-string form
        # (/search/?query=<q>) is a status-dashboard stub with no results.
        return f"{SITE_URLS['knaben']}/search/{quote(query)}"

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        url = self._build_url(query)
        try:
            client = await self._get_client()
            resp = await client.get(url)
            if resp.status_code in (403, 429, 503):
                return []
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            return []

        results = []
        for row in soup.find_all("tr"):
            # Only real result rows carry a magnet anchor in the title cell.
            anchor = row.select_one("a[href^='magnet:']")
            if anchor is None:
                continue
            tds = row.find_all("td")
            if len(tds) < 6:
                continue
            title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            magnet = anchor.get("href", "")

            hash_match = _INFO_HASH_RE.search(magnet)
            # tds[0] category, tds[1] title, tds[2] size, tds[3] date,
            # tds[4] seeders, tds[5] leechers; tds[6] origin link skipped.
            results.append(SearchResult(
                title=title,
                source=Source.KNABEN,
                category=tds[0].get_text(" ", strip=True),
                size_bytes=parse_size(tds[2].get_text(" ", strip=True)),
                seeders=to_int(tds[4].get_text(" ", strip=True)),
                leechers=to_int(tds[5].get_text(" ", strip=True)),
                magnet=magnet,
                info_hash=hash_match.group(1) if hash_match else "",
                added=tds[3].get_text(" ", strip=True),
                torrent_url="",
                page_url="",
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{SITE_URLS['knaben']}/")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
