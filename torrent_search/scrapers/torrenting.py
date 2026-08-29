"""Torrenting.com torrent scraper (HTML).

Anonymous search may be gated by a login wall; in that case no result
containers exist and search() returns an empty list.
"""

import re
import httpx
from bs4 import BeautifulSoup
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size, to_int

SIZE_RE = re.compile(r"([\d.,]+)\s*(GB|MB|KB|GiB|MiB|KiB)\b", re.IGNORECASE)
SEED_RE = re.compile(r"(?:^|[^\w])(?:s|seeds?)\s*[:=]?\s*(\d+)", re.IGNORECASE)
LEECH_RE = re.compile(r"(?:^|[^\w])(?:l|leechers?)\s*[:=]?\s*(\d+)", re.IGNORECASE)
NAV_WORDS = {"sign in", "log in", "login", "register", "password", "forgot", "sign up", "home"}


class TorrentingScraper(BaseScraper):
    source = Source.TORRENTING

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

    def _extract_seeds(self, text: str) -> tuple[int, int]:
        sm = SEED_RE.search(text)
        lm = LEECH_RE.search(text)
        if sm:
            seeds = int(sm.group(1))
        else:
            nums = re.findall(r"\d[\d,]*", text)
            seeds = int(nums[0].replace(",", "")) if nums else 0
        leechers = int(lm.group(1)) if lm else 0
        return seeds, leechers

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        url = f"{SITE_URLS['torrenting']}/search/?q={query}"
        try:
            client = await self._get_client()
            resp = await client.get(url)
            if resp.status_code in (403, 429, 503):
                return []
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            return []

        qlower = query.lower()
        results = []
        seen = set()

        containers = (
            soup.select(".search-result, .result-item, .result, .torrent-item")
            or soup.find_all("div", recursive=True)
        )

        for container in containers:
            link = container.find("a", href=True)
            if link is None:
                continue
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if not title or len(title) < 8 or href in seen:
                continue
            seen.add(href)

            tlower = title.lower()
            if tlower in NAV_WORDS or not (qlower in tlower or "torrent" in tlower):
                continue

            text = container.get_text(" ", strip=True)
            size_bytes = parse_size(text)
            if size_bytes == 0:
                m = SIZE_RE.search(text)
                if m:
                    size_bytes = parse_size(m.group(0))
            seeders, leechers = self._extract_seeds(text)

            full = href if href.startswith("http") else f"{SITE_URLS['torrenting']}{href}"
            results.append(SearchResult(
                title=title,
                source=Source.TORRENTING,
                category=kwargs.get("category", ""),
                size_bytes=size_bytes,
                seeders=seeders,
                leechers=leechers,
                torrent_url=full,
                page_url=full,
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{SITE_URLS['torrenting']}/")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
