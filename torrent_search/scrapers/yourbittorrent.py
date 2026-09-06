"""YourBittorrent.com torrent scraper (HTML)."""

import re

import httpx
from bs4 import BeautifulSoup
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size, to_int

# Site blocks the default Chrome UA; Firefox UA verified working.
USER_AGENT_FIREFOX = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
    "Gecko/20100101 Firefox/130.0"
)

# Real result rows carry a title anchor "yb-tname" with a RELATIVE
# /torrent/<id>/<slug>/ href. Injected spam rows (t0r.space links with
# "Full Version" / "Complete Pack" titles) never satisfy both conditions,
# so they are dropped here.
_TORRENT_HREF_RE = re.compile(r"^/torrent/(\d+)/")


def _cell_text(row, selector: str) -> str:
    td = row.select_one(selector)
    return td.get_text(" ", strip=True) if td else ""


class YourBittorrentScraper(BaseScraper):
    source = Source.YOURBITTORRENT

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": USER_AGENT_FIREFOX},
                follow_redirects=True,
            )
        return self._client

    def _build_url(self, query: str, **kwargs) -> str:
        return f"{SITE_URLS['yourbittorrent']}/?q={query}"

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

        base = SITE_URLS["yourbittorrent"]
        results = []
        for row in soup.find_all("tr"):
            link = row.select_one("a.yb-tname[href]")
            if link is None:
                continue
            href = link.get("href", "")
            id_match = _TORRENT_HREF_RE.match(href)
            if id_match is None:
                continue
            torrent_id = id_match.group(1)

            cat_link = row.select_one("a.yb-cat")
            if cat_link is None:
                continue
            category = cat_link.get("title") or cat_link.get_text(" ", strip=True)
            upl_link = row.select_one("a.yb-upl")
            uploader = upl_link.get_text(" ", strip=True) if upl_link else ""

            results.append(SearchResult(
                title=link.get_text(" ", strip=True),
                source=Source.YOURBITTORRENT,
                category=category,
                size_bytes=parse_size(_cell_text(row, "td[data-label='Size']")),
                seeders=to_int(_cell_text(row, "td[data-label='Seed']")),
                leechers=to_int(_cell_text(row, "td[data-label='Peers']")),
                added=_cell_text(row, "td[data-label='Added']"),
                uploader=uploader,
                torrent_url=f"{base}/down/{torrent_id}.torrent",
                page_url=f"{base}{href}",
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{SITE_URLS['yourbittorrent']}/")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
