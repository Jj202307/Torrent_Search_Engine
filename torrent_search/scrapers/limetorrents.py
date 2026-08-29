"""LimeTorrents.lol torrent scraper (HTML)."""

import httpx
from bs4 import BeautifulSoup
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size, to_int

CATEGORIES = ["movies", "tv-shows", "music", "games", "applications", "anime", "other"]


class LimeTorrentsScraper(BaseScraper):
    source = Source.LIMETORRENTS

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

    def _build_url(self, query: str, **kwargs) -> str:
        category = kwargs.get("category")
        if category and category in CATEGORIES:
            return f"{SITE_URLS['limetorrents']}/search/{category}/{query}/"
        return f"{SITE_URLS['limetorrents']}/search/all/{query}/"

    @staticmethod
    def _join(base: str, href: str) -> str:
        if not href:
            return ""
        return href if href.startswith("http") else f"{base}{href}"

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        url = self._build_url(query, **kwargs)
        try:
            client = await self._get_client()
            resp = await client.get(url)
            if resp.status_code in (403, 429, 503):
                return []
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            return []

        base = SITE_URLS["limetorrents"]
        results = []
        for row in soup.select("table.table2 tr"):
            tdleft = row.find("td", class_="tdleft")
            if not tdleft:
                continue
            link = next(
                (a for a in tdleft.find_all("a", href=True) if a.get("href", "").startswith("/")),
                None,
            )
            if link is None:
                continue
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if not title:
                continue

            seeds_td = row.find("td", class_="tdseed")
            leech_td = row.find("td", class_="tdleech")
            size_td = next(
                (td for td in row.find_all("td", class_="tdnormal")[1:] if parse_size(td.get_text())),
                None,
            )

            results.append(SearchResult(
                title=title,
                source=Source.LIMETORRENTS,
                category=kwargs.get("category", ""),
                size_bytes=parse_size(size_td.get_text()) if size_td else 0,
                seeders=to_int(seeds_td.get_text()) if seeds_td else 0,
                leechers=to_int(leech_td.get_text()) if leech_td else 0,
                torrent_url=self._join(base, href),
                page_url=self._join(base, href),
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{SITE_URLS['limetorrents']}/")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
