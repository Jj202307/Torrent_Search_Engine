"""1337x.to torrent scraper (HTML)."""

import httpx
from bs4 import BeautifulSoup
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size, to_int

CATEGORIES = [
    "movies", "tv", "music", "games",
    "apps", "anime", "documentaries", "other",
]

SORT_FIELDS = {"seeders", "leechers", "size", "time"}
SORT_ORDERS = {"asc", "desc"}


class X1337Scraper(BaseScraper):
    source = Source.X1337

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
        base = SITE_URLS["x1337"]
        category = kwargs.get("category")
        sort_field = kwargs.get("sort_field", "seeders")
        sort_order = kwargs.get("sort_order", "desc")
        page = int(kwargs.get("page", 1) or 1)

        sort_field = sort_field if sort_field in SORT_FIELDS else "seeders"
        sort_order = sort_order if sort_order in SORT_ORDERS else "desc"

        if category and category in CATEGORIES:
            path = f"/category-search/{query}/{category}/{page}/"
        else:
            path = f"/search/{query}/{page}/"
        return f"{base}{path}sort-{sort_field}-{sort_order}/"

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
        rows = soup.select("tbody tr")
        for row in rows:
            name_td = row.select_one("td.name")
            if not name_td:
                continue
            links = name_td.find_all("a", href=True)
            if not links:
                continue
            torrent_link = links[-1]
            href = torrent_link.get("href", "")
            if not href.startswith("/torrent/"):
                continue

            title = torrent_link.get_text(strip=True)
            if not title:
                continue

            seeds_td = row.select_one("td.coll-2.seeds")
            leeches_td = row.select_one("td.coll-3.leeches")
            size_td = row.select_one("td.coll-4.size")

            seeders = to_int(seeds_td.get_text(strip=True)) if seeds_td else 0
            leechers = to_int(leeches_td.get_text(strip=True)) if leeches_td else 0
            size_bytes = parse_size(size_td.get_text(strip=True)) if size_td else 0

            results.append(SearchResult(
                title=title,
                source=Source.X1337,
                category=kwargs.get("category", ""),
                size_bytes=size_bytes,
                seeders=seeders,
                leechers=leechers,
                torrent_url=f"{SITE_URLS['x1337']}{href}",
                page_url=f"{SITE_URLS['x1337']}{href}",
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{SITE_URLS['x1337']}/")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
