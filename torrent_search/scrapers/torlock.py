"""TorLock.com torrent scraper (HTML)."""

import httpx
from bs4 import BeautifulSoup
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size, to_int

CATEGORY_SUFFIX = {
    "movies": "movies",
    "tv": "tv",
    "music": "music",
    "games": "games",
    "software": "software",
    "apps": "software",
    "anime": "anime",
    "ebooks": "ebooks",
    "books": "ebooks",
    "images": "images",
    "adult": "adult",
}


class TorLockScraper(BaseScraper):
    source = Source.TORLOCK

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
        base = SITE_URLS["torlock"]
        category = kwargs.get("category")
        suffix = CATEGORY_SUFFIX.get(category, "torrents") if category else "torrents"
        return f"{base}/all/{suffix}/{query}.html"

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

        results = []
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue
                link = next(
                    (a for a in row.find_all("a", href=True) if a.get_text(strip=True)),
                    None,
                )
                if link is None:
                    continue
                href = link.get("href", "")
                title = link.get_text(strip=True)

                size_text = cells[3].get_text(" ", strip=True) if len(cells) > 3 else ""
                seeds_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                peers_text = cells[5].get_text(strip=True) if len(cells) > 5 else ""

                results.append(SearchResult(
                    title=title,
                    source=Source.TORLOCK,
                    category=kwargs.get("category", ""),
                    size_bytes=parse_size(size_text),
                    seeders=to_int(seeds_text),
                    leechers=to_int(peers_text),
                    torrent_url=f"{SITE_URLS['torlock']}{href}" if href.startswith("/") else href,
                    page_url=f"{SITE_URLS['torlock']}{href}" if href.startswith("/") else href,
                ))
                if len(results) >= MAX_RESULTS_PER_SOURCE:
                    break
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{SITE_URLS['torlock']}/")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
