"""Katcr.co scraper. KickassTorrents revival, table-based HTML."""

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

SEARCH_URL = f"{SITE_URLS['katcr']}/katsearch.php"

SORT_MAP = {
    "seeders": "seeders",
    "leechers": "leechers",
    "size": "size",
    "date": "date",
    "name": "name",
}


def re_fullmatch_digits(text: str) -> bool:
    stripped = text.replace(",", "").replace(" ", "")
    return stripped.isdigit() and bool(stripped)


class KatCRScraper(BaseScraper):
    source = Source.KATCR

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
                    "Referer": SITE_URLS["katcr"],
                },
                follow_redirects=True,
            )
        return self._client

    def _parse_html(self, html: str, category: str = "") -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        rows = soup.select("table tr")
        if not rows:
            rows = soup.select(".data tr") or soup.select("tr[class]")

        for row in rows:
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
            cells = row.find_all("td")
            if not cells:
                continue
            try:
                cell_text = row.get_text(" ", strip=True)
                if not cell_text or "magnet" not in row.get_text().lower() and not row.select_one("a[href^='magnet:']"):
                    magnet_a = row.select_one("a[href^='magnet:']")
                    if magnet_a is None:
                        continue

                magnet = ""
                magnet_a = row.select_one("a[href^='magnet:']")
                if magnet_a:
                    magnet = magnet_a["href"]

                title_el = row.select_one("a[href*='torrent']") or row.select_one("a[href*='?']")
                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not title:
                    title = cell_text.split("Magnet")[0].strip()[:200]
                if not title:
                    continue

                page_url = ""
                if title_el and title_el.get("href"):
                    href = title_el["href"]
                    if href.startswith("http"):
                        page_url = href
                    else:
                        page_url = f"{SITE_URLS['katcr']}{href if href.startswith('/') else '/' + href}"

                torrent_url = ""
                for a in row.find_all("a", href=True):
                    if a["href"].endswith(".torrent") or "/download" in a["href"]:
                        torrent_url = a["href"]
                        break

                size_bytes = parse_size(cell_text)

                seeders = leechers = 0
                numeric_cells = []
                for c in cells:
                    t = c.get_text(" ", strip=True)
                    if re_fullmatch_digits(t):
                        numeric_cells.append(t)
                if len(numeric_cells) >= 2:
                    seeders = to_int(numeric_cells[0])
                    leechers = to_int(numeric_cells[1])
                elif len(numeric_cells) == 1:
                    seeders = to_int(numeric_cells[0])

                added = ""
                for c in cells:
                    t = c.get_text(" ", strip=True)
                    if any(k in t.lower() for k in ("ago", ":")) or ("-" in t and any(ch.isdigit() for ch in t)):
                        if len(t) < 40:
                            added = t
                            break

                results.append(SearchResult(
                    title=title,
                    source=self.source,
                    category=category,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    magnet=magnet,
                    torrent_url=torrent_url,
                    added=added,
                    page_url=page_url,
                ))
            except Exception:
                continue
        return results

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        category = kwargs.get("category")
        sort = kwargs.get("sort")
        if sort and sort.lower() in SORT_MAP:
            sort = SORT_MAP[sort.lower()]

        params = {"q": query, "field": "torrents"}
        if category:
            params["category"] = category
        if sort:
            params["order"] = sort

        client = await self._get_client()
        try:
            resp = await client.get(SEARCH_URL, params=params)
            resp.raise_for_status()
            return self._parse_html(resp.text, category=category)
        except Exception:
            return []

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(SITE_URLS["katcr"])
            resp.raise_for_status()
            return 200 <= resp.status_code < 400
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
