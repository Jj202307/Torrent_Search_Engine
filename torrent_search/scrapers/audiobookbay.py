"""AudioBookBay (audiobookbay.lu) torrent scraper (HTML)."""

import asyncio
import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size

# File Size lives in a colored span, e.g. <span style="color:#00f;">4.39</span> GBs
# (rendered unit may carry a trailing 's').
_FILE_SIZE_RE = re.compile(
    r"File Size:\s*<span[^>]*>\s*([\d.,]+)\s*</span>\s*(GB|MB)", re.IGNORECASE
)
_INFO_HASH_RE = re.compile(r"urn:btih:([a-fA-F0-9]{32,40})")
# Live detail pages publish the raw hash in the details table (<td>Info Hash:</td>
# <td><40-hex></td>) with no magnet anchor; rebuild the magnet from it.
_DETAIL_HASH_RE = re.compile(
    r"Info Hash:\s*</td>\s*<td>\s*([a-fA-F0-9]{32,40})", re.IGNORECASE
)
_MAGNET_FETCH_CONCURRENCY = 4


def _posted_date(post_div) -> str:
    strings = list(post_div.stripped_strings)
    for i, s in enumerate(strings):
        if "Posted:" in s:
            rest = s.split("Posted:", 1)[1].strip()
            if rest:
                return rest
            if i + 1 < len(strings):
                return strings[i + 1]
    return ""


class AudioBookBayScraper(BaseScraper):
    source = Source.AUDIOBOOKBAY

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
        return f"{SITE_URLS['audiobookbay']}/?s={query}"

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

        base = SITE_URLS["audiobookbay"]
        results = []
        for post_div in soup.find_all("div", class_="post"):
            link = post_div.select_one("div.postTitle h2 a[href]")
            if link is None:
                continue
            href = link.get("href", "")
            if not href.startswith("/abss/"):
                continue

            size_match = _FILE_SIZE_RE.search(str(post_div))
            if size_match:
                unit = size_match.group(2).rstrip("s")
                size_bytes = parse_size(f"{size_match.group(1)} {unit}")
            else:
                size_bytes = 0

            categories = [
                a.get_text(" ", strip=True)
                for a in post_div.select("a[rel~='category']")
                if a.get_text(" ", strip=True)
            ]

            results.append(SearchResult(
                title=link.get_text(" ", strip=True),
                source=Source.AUDIOBOOKBAY,
                category=", ".join(categories),
                size_bytes=size_bytes,
                seeders=0,
                leechers=0,
                page_url=f"{base}{href}",
                added=_posted_date(post_div),
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        # Magnets are only available on detail pages; fetch them concurrently.
        sem = asyncio.Semaphore(_MAGNET_FETCH_CONCURRENCY)

        async def fetch_detail(page_url: str, title: str) -> tuple[str, str, str]:
            try:
                async with sem:
                    client = await self._get_client()
                    resp = await client.get(page_url)
                    if resp.status_code in (403, 429, 503):
                        return "", "", ""
                    resp.raise_for_status()
                detail = BeautifulSoup(resp.text, "html.parser")
                detail_str = str(detail)
                magnet, info_hash, torrent_url = "", "", ""

                anchor = detail.select_one('a[href^="magnet:"]')
                if anchor is not None:
                    magnet = anchor.get("href", "")
                    hash_match = _INFO_HASH_RE.search(magnet)
                    if hash_match:
                        info_hash = hash_match.group(1)
                else:
                    # Live pages publish the hash in the details table instead.
                    hash_match = _DETAIL_HASH_RE.search(detail_str)
                    if hash_match:
                        info_hash = hash_match.group(1)
                        magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={quote(title)}"

                dl_link = detail.select_one('a[href^="/downld0"]')
                if dl_link is not None:
                    torrent_url = f"{base}{dl_link.get('href', '')}"
                return magnet, info_hash, torrent_url
            except Exception:
                return "", "", ""

        details = await asyncio.gather(
            *(fetch_detail(r.page_url, r.title) for r in results)
        )
        for result, (magnet, info_hash, torrent_url) in zip(results, details):
            result.magnet = magnet
            result.info_hash = info_hash
            result.torrent_url = torrent_url

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{SITE_URLS['audiobookbay']}/")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
