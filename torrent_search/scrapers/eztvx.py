"""EZTVx.to scraper. TV show torrents, RSS-first with HTML fallback."""

import re
import xml.etree.ElementTree as ET

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

RSS_URL = f"{SITE_URLS['eztvx']}/ezrss.xml"
SEARCH_URL = f"{SITE_URLS['eztvx']}/search/{{query}}"

_NS = {
    "torrent": "http://xmlns.ezrss.it/0.1/",
}


class EZTVXScraper(BaseScraper):
    source = Source.EZTVX

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "application/xml,text/html,*/*",
                },
                follow_redirects=True,
            )
        return self._client

    def _parse_rss(self, xml_text: str) -> list[SearchResult]:
        root = ET.fromstring(xml_text)
        results = []
        for item in root.iter("item"):
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
            try:
                title_el = item.find("title")
                link_el = item.find("link")
                enclosure_el = item.find("enclosure")
                seeds_el = item.find("torrent:seeds", _NS)
                peers_el = item.find("torrent:peers", _NS)
                size_el = item.find("torrent:size", _NS)

                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                if not title:
                    continue
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                magnet = enclosure_el.get("url", "") if enclosure_el is not None else ""
                if magnet.startswith("magnet:"):
                    link = magnet
                size_bytes = parse_size(size_el.text or "") if size_el is not None and size_el.text else 0
                seeders = to_int(seeds_el.text or "") if seeds_el is not None and seeds_el.text else 0
                leechers = to_int(peers_el.text or "") if peers_el is not None and peers_el.text else 0

                results.append(SearchResult(
                    title=title,
                    source=self.source,
                    category="tv",
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    magnet=magnet,
                    torrent_url=link if not link.startswith("magnet:") else "",
                ))
            except Exception:
                continue
        return results

    def _parse_html(self, html: str) -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        rows = soup.select("tr")
        if not rows:
            rows = soup.select(".forum_header_border tr") or soup.select("table tr")
        for row in rows:
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
            cells = row.find_all("td")
            if not cells:
                continue
            try:
                cell_text = row.get_text(" ", strip=True)
                title_el = row.select_one("a.magnet") or row.select_one("a[href*='torrents/']")
                if title_el is None:
                    title_el = row.select_one("a")
                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not title:
                    continue
                magnet = ""
                magnet_el = row.select_one("a.magnet")
                if magnet_el and magnet_el.get("href", "").startswith("magnet:"):
                    magnet = magnet_el["href"]
                elif magnet_el:
                    magnet = magnet_el.get("href", "")

                torrent_url = ""
                for a in row.find_all("a", href=True):
                    href = a["href"]
                    if "torrents/" in href and href.endswith(".torrent"):
                        torrent_url = href
                        break

                size_bytes = parse_size(cell_text)
                seeders = leechers = 0
                nums = re.findall(r"\d[\d,]*", cell_text)
                if len(nums) >= 3:
                    seeders = to_int(nums[-2])
                    leechers = to_int(nums[-1])

                results.append(SearchResult(
                    title=title,
                    source=self.source,
                    category="tv",
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    magnet=magnet,
                    torrent_url=torrent_url,
                ))
            except Exception:
                continue
        return results

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        client = await self._get_client()
        try:
            resp = await client.get(RSS_URL, params={"q": query, "imdb": "", "rss": "1"})
            resp.raise_for_status()
            results = self._parse_rss(resp.text)
            if results:
                return results
        except Exception:
            pass

        try:
            resp = await client.get(SEARCH_URL.format(query=query))
            resp.raise_for_status()
            return self._parse_html(resp.text)
        except Exception:
            return []

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(RSS_URL, params={"q": "test"})
            resp.raise_for_status()
            return "rss" in resp.text.lower() or "item" in resp.text.lower()
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
