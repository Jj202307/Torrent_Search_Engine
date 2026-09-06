"""YTS movie torrent scraper via yts.mx / yts.bz API."""

import asyncio

import httpx
from ..base import BaseScraper, SearchResult, Source
from ..config import SITE_URLS, DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, MAX_RESULTS_PER_SOURCE
from ..normalizer import parse_size

class YTSScraper(BaseScraper):
    source = Source.YTS
    # Empty query = browse: the API omits query_term and returns all
    # movies newest-first (sort_by=date_added desc is the server default).
    supports_browse = True

    # YTS quality ↔ API param mapping
    QUALITY_MAP = {"720p": "720p", "1080p": "1080p", "2160p": "2160p", "3d": "3D", "4k": "2160p"}

    # Mirror quirks (live-verified 2026-09-06, movies-api.accel.li):
    # - any limit>50 clamps to 20 movies server-side; only limit=50 returns
    #   a full page, so requests always use PAGE_SIZE and we paginate;
    # - `page` paging is clean (no overlap/gaps) in browse and keyword modes;
    # - past the end the response is HTTP 200 with the `movies` key ABSENT;
    # - sort_by=download_count/rating/year/title honored; sort_by=seeds is
    #   silently ignored (falls back to date_added).
    PAGE_SIZE = 50      # API max usable page size
    MAX_PAGES = 20      # sane ceiling: 1000 movies / ~2000 torrent rows
    PAGE_DELAY = 0.35   # politeness between page requests

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
        # Fetch window in rows (≈2 torrents/movie). CLI passes --limit here;
        # MAX_RESULTS_PER_SOURCE is the module global, patched by
        # config.set_max_results_per_source() — always read at call time.
        window = min(kwargs.get("limit", MAX_RESULTS_PER_SOURCE), MAX_RESULTS_PER_SOURCE)
        if window <= 0:
            return []

        # Never send the window as the API `limit` — clamp per call instead
        # and loop pages (see PAGE_SIZE/MAX_PAGES notes above).
        params: dict = {"limit": self.PAGE_SIZE}
        # Omit query_term entirely when empty — sending "" also works, but
        # omission is the documented browse form and both return newest-first.
        if query:
            params["query_term"] = query

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

        url = f"{SITE_URLS['yts_api']}/list_movies.json"
        client = await self._get_client()

        # A `page` kwarg (standalone callers) shifts the whole loop; the CLI
        # path leaves it unset and we start from page 1.
        start_page = int(kwargs.get("page") or 1)

        results: list[SearchResult] = []
        seen: set[tuple] = set()

        for page_no in range(start_page, start_page + self.MAX_PAGES):
            try:
                resp = await client.get(url, params={**params, "page": page_no})
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                # Page-1 failure -> []; mid-loop failure -> partial results.
                return results
            if data.get("status") != "ok":
                return results

            payload = data.get("data", {}) or {}
            # `movies` key is ABSENT (not []) past the end of the result set.
            movies = payload.get("movies") or []
            if not movies:
                break
            movie_count = payload.get("movie_count") or 0

            for movie in movies:
                movie_title = movie.get("title_long") or movie.get("title", "")
                movie_year = movie.get("year", "")
                movie_rating = movie.get("rating", 0)
                genres = movie.get("genres", [])
                genre_str = ", ".join(genres) if genres else ""
                movie_id = movie.get("id")

                for torrent in movie.get("torrents", []):
                    if len(results) >= window:
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
                    key = (movie_id, t_hash)
                    if key in seen:
                        continue
                    magnet = f"magnet:?xt=urn:btih:{t_hash}&dn={movie_title}&tr=udp://tracker.openbittorrent.com:80" if t_hash else ""

                    display_title = f"{movie_title} ({movie_year}) [{quality}] [Rating: {movie_rating}]"
                    if genres:
                        display_title += f" [{genre_str}]"

                    seen.add(key)
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

                if len(results) >= window:
                    break

            if len(results) >= window:
                return results[:window]
            # Stop when the server says the result set is exhausted.
            if movie_count and page_no * self.PAGE_SIZE >= movie_count:
                break
            await asyncio.sleep(self.PAGE_DELAY)

        return results[:window]

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
