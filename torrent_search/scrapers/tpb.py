"""TPB scraper via apibay.org JSON API."""

import httpx
from datetime import datetime
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE

class TPBScraper(BaseScraper):
    source = Source.TPB

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            )
        return self._client

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        category = kwargs.get("category")
        params = {"q": query}
        if category:
            params["cat"] = category
        url = f"{SITE_URLS['tpb_api']}/q.php"

        try:
            client = await self._get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        results = []
        for item in data[:MAX_RESULTS_PER_SOURCE]:
            try:
                added_ts = int(item.get("added", 0))
                added_str = datetime.utcfromtimestamp(added_ts).strftime("%Y-%m-%d") if added_ts else ""
                size_bytes = int(item.get("size", 0))
                seeders = int(item.get("seeders", 0))
                leechers = int(item.get("leechers", 0))
                info_hash = item.get("info_hash", "")
                name = item.get("name", "")

                results.append(SearchResult(
                    title=name,
                    source=Source.TPB,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    info_hash=info_hash,
                    magnet=f"magnet:?xt=urn:btih:{info_hash}&dn={name}" if info_hash else "",
                    added=added_str,
                    uploader=item.get("username", ""),
                    page_url=f"{SITE_URLS['tpb']}/description.php?id={item.get('id', '')}" if item.get("id") else "",
                ))
            except Exception:
                continue

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{SITE_URLS['tpb_api']}/q.php",
                params={"q": "test", "cat": "0"},
            )
            data = resp.json()
            return isinstance(data, list)
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
