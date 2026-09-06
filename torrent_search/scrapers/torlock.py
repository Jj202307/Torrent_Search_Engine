"""TorLock.com torrent scraper (HTML)."""

import re

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

# Real result rows link to /torrent/<id>/<slug>.html detail pages; the direct
# .torrent file is served from TorLock's download mirror as /tor/<id>.torrent.
_TORRENT_ID_RE = re.compile(r"/torrent/(\d+)/")
DOWNLOAD_URL = "https://lt.t0r.space/tor/{id}.torrent"


def _cell_text(row, cls: str) -> str:
    td = row.select_one(f"td.{cls}")
    return td.get_text(" ", strip=True) if td else ""


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
        for row in soup.find_all("tr"):
            # Only real result rows carry a title link with class "tl-name".
            # Ad-banner rows and injected mirror-spam rows (t0r.space links
            # with "Full Version" / "High-Definition" titles that 404) don't,
            # so they are dropped here.
            link = row.select_one("a.tl-name[href]")
            if link is None:
                continue
            href = link.get("href", "")
            id_match = _TORRENT_ID_RE.search(href)
            if id_match is None:
                continue

            page_url = href if href.startswith("http") else f"{SITE_URLS['torlock']}{href}"
            results.append(SearchResult(
                title=link.get_text(" ", strip=True),
                source=Source.TORLOCK,
                category=kwargs.get("category", ""),
                size_bytes=parse_size(_cell_text(row, "ts")),
                seeders=to_int(_cell_text(row, "tul")),
                leechers=to_int(_cell_text(row, "tdl")),
                torrent_url=DOWNLOAD_URL.format(id=id_match.group(1)),
                page_url=page_url,
            ))
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
