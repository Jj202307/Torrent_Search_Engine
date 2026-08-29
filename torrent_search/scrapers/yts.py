"""YTS movie torrent scraper via yts.mx / yts.bz API."""

import httpx
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size

class YTSScraper(BaseScraper):
    source = Source.YTS

    # YTS quality ↔ API param mapping
    QUALITY_MAP = {"720p": "720p", "1080p": "1080p", "2160p": "2160p", "3d": "3D", "4k": "2160p"}

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
        params: dict = {
            "query_term": query,
            "limit": min(kwargs.get("limit", 20), MAX_RESULTS_PER_SOURCE),
        }

        # Map quality param
        if "quality" in kwargs:
            mapped = self.QUALITY_MAP.get(kwargs["quality"].lower())
            if mapped:
                params["quality"] = mapped
            elif kwargs["quality"].lower() == "all":
                params["quality"] = "all"

        if "genre" in kwargs:
            params["genre"] = kwargs["genre"]
        if "minimum_rating" in kwargs:
            params["minimum_rating"] = int(kwargs["minimum_rating"])
        if "sort_by" in kwargs:
            params["sort_by"] = kwargs["sort_by"]
        if "page" in kwargs:
            params["page"] = kwargs["page"]

        url = f"{SITE_URLS['yts_api']}/list_movies.json"

        try:
            client = await self._get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        if data.get("status") != "ok":
            return []

        movies = data.get("data", {}).get("movies", [])
        if not movies:
            return []

        results = []
        for movie in movies:
            movie_title = movie.get("title_long") or movie.get("title", "")
            movie_year = movie.get("year", "")
            movie_rating = movie.get("rating", 0)
            genres = movie.get("genres", [])
            genre_str = ", ".join(genres) if genres else ""
            imdb_code = movie.get("imdb_code", "")

            for torrent in movie.get("torrents", []):
                if len(results) >= MAX_RESULTS_PER_SOURCE:
                    break

                quality = torrent.get("quality", "")
                t_size = torrent.get("size", "")
                size_bytes = parse_size(t_size)
                if size_bytes == 0 and t_size:
                    # fallback parse
                    try:
                        import re
                        m = re.match(r"([\d.]+)\s*(\w+)", t_size)
                        if m:
                            val = float(m.group(1))
                            unit = m.group(2).upper()
                            mult = {"GB": 1024**3, "MB": 1024**2, "KB": 1024}.get(unit, 1)
                            size_bytes = int(val * mult)
                    except Exception:
                        size_bytes = 0

                seeds = int(torrent.get("seeds", 0))
                peers = int(torrent.get("peers", 0))
                t_hash = torrent.get("hash", "")
                magnet = f"magnet:?xt=urn:btih:{t_hash}&dn={movie_title}&tr=udp://tracker.openbittorrent.com:80" if t_hash else ""

                display_title = f"{movie_title} ({movie_year}) [{quality}] [Rating: {movie_rating}]"
                if genres:
                    display_title += f" [{genre_str}]"

                results.append(SearchResult(
                    title=display_title,
                    source=Source.YTS,
                    category=genre_str,
                    size_bytes=size_bytes,
                    seeders=seeds,
                    leechers=peers,
                    magnet=magnet,
                    torrent_url=torrent.get("url", ""),
                    info_hash=t_hash,
                    added=torrent.get("date_uploaded", ""),
                    page_url=f"{SITE_URLS['yts']}/movie/{movie.get('slug', '')}" if movie.get("slug") else "",
                ))

            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break

        return results

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{SITE_URLS['yts_api']}/list_movies.json",
                params={"query_term": "test", "limit": 1},
            )
            data = resp.json()
            return data.get("status") == "ok"
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
