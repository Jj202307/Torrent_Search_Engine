"""YggTorrent torrent scraper (login required)."""

import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlencode, urljoin

from ..base import BaseScraper, SearchResult, Source
from ..config import (
    SITE_URLS,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    MAX_RESULTS_PER_SOURCE,
    CREDENTIALS,
)
from ..normalizer import parse_size

BASE_URL = SITE_URLS["yggtorrent"]
LOGIN_URL = f"{BASE_URL}/user/login"
SEARCH_URL = f"{BASE_URL}/engine/search"

CATEGORY_IDS = {
    "films": "2140",
    "series": "2141",
    "musique": "2142",
    "music": "2142",
    "jeux-video": "2143",
    "games": "2143",
    "applications": "2144",
    "apps": "2144",
    "ebooks": "2145",
    "books": "2145",
    "animation": "2146",
    "anime": "2146",
}

USER_FIELDS = ("login_username", "username", "user", "login", "id")
PASS_FIELDS = ("login_password", "password", "pass", "passwd")

_FR_UNITS = {"to": "TB", "go": "GB", "mo": "MB", "ko": "KB", "o": "B"}


def _decode(resp: httpx.Response) -> str:
    enc = resp.encoding
    if enc and enc.lower() not in ("utf-8", "utf8", "ascii"):
        try:
            return resp.content.decode(enc, errors="replace")
        except LookupError:
            pass
    for e in ("utf-8", "windows-1251"):
        try:
            return resp.content.decode(e)
        except (UnicodeDecodeError, LookupError):
            continue
    return resp.text


def _digits(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _abs(base: str, href: str) -> str:
    return urljoin(base, href)


def _parse_size(text: str) -> int:
    m = re.search(r"([\d.,]+)\s*([TGMK]?o)\b", text, re.IGNORECASE)
    if m:
        unit = _FR_UNITS.get(m.group(2).lower())
        if unit:
            return parse_size(f"{m.group(1)} {unit}")
    return parse_size(text)


def _has_login_form(html: str) -> bool:
    return any(f'name="{n}"' in html for n in USER_FIELDS + PASS_FIELDS)


def _login_payload(html: str, creds: dict) -> tuple[dict, str | None]:
    soup = BeautifulSoup(html, "lxml")
    form = soup.select_one("form[method='post']") or soup.find("form")
    action = form.get("action") if form else None
    names = {inp.get("name") for inp in form.find_all("input") if inp.get("name")} if form else set()
    user_field = next((n for n in USER_FIELDS if n in names), "username")
    pass_field = next((n for n in PASS_FIELDS if n in names), "password")
    data = {user_field: creds["username"], pass_field: creds["password"]}
    if form:
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name or name in data:
                continue
            typ = (inp.get("type") or "").lower()
            if typ in ("hidden", "submit"):
                data[name] = inp.get("value", "")
    return data, action


class YggTorrentScraper(BaseScraper):
    source = Source.YGGTORRENT

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._logged_in = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
            )
        return self._client

    async def _login(self) -> bool:
        if self._logged_in:
            return True
        creds = CREDENTIALS.get(self.source.value, {})
        if not creds.get("username") or not creds.get("password"):
            return False
        client = await self._get_client()
        try:
            page = await client.get(LOGIN_URL)
            html = self._decode(page)
            data, _ = _login_payload(html, creds)
            resp = await client.post(LOGIN_URL, data=data)
            if resp.status_code >= 400:
                return False
            self._logged_in = "login" not in str(resp.url).lower()
        except Exception:
            return False
        return self._logged_in

    def _parse_results(self, html: str, category: str = "", base_url: str | None = None) -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        base = base_url or BASE_URL
        results = []
        for tr in soup.select("table.table tr, #torrent-list tr, tbody tr"):
            link = tr.select_one("a[href*='/torrent/']")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            if not title:
                continue
            href = link.get("href", "")
            page_url = _abs(base, href)
            cells = tr.find_all("td")
            cat = category
            if not cat and cells and cells[0].find("img"):
                img = cells[0].find("img")
                cat = img.get("title") or img.get("alt") or ""
            size_bytes = _parse_size(tr.get_text(" ", strip=True))
            seeders = leechers = 0
            added = ""
            seed_td = tr.select_one(".stat-seed, [class*='seed']")
            leech_td = tr.select_one(".stat-leech, [class*='leech']")
            if seed_td:
                seeders = _digits(seed_td.get_text(" ", strip=True))
            if leech_td:
                leechers = _digits(leech_td.get_text(" ", strip=True))
            date_td = tr.select_one("[class*='date']")
            if date_td:
                added = date_td.get_text(" ", strip=True)
            if seeders == 0 and leechers == 0:
                size_idx = next(
                    (i for i, td in enumerate(cells) if _parse_size(td.get_text(" ", strip=True)) > 0),
                    -1,
                )
                if size_idx >= 0:
                    if size_idx + 1 < len(cells):
                        seeders = _digits(cells[size_idx + 1].get_text(" ", strip=True))
                    if size_idx + 2 < len(cells):
                        leechers = _digits(cells[size_idx + 2].get_text(" ", strip=True))
            results.append(SearchResult(
                title=title,
                source=self.source,
                category=cat,
                size_bytes=size_bytes,
                seeders=seeders,
                leechers=leechers,
                torrent_url=page_url,
                page_url=page_url,
                added=added,
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
        return results

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        if not await self._login():
            return []
        category = kwargs.get("category")
        cat_id = None
        if category:
            if str(category).isdigit():
                cat_id = str(category)
            else:
                cat_id = CATEGORY_IDS.get(str(category).lower())
        params = {"name": query, "do": "search"}
        if cat_id:
            params["category"] = cat_id
        client = await self._get_client()
        try:
            resp = await client.get(f"{SEARCH_URL}?{urlencode(params)}")
            if resp.status_code in (403, 429, 503):
                return []
            resp.raise_for_status()
            return self._parse_results(self._decode(resp), cat_id or "", str(resp.url))
        except Exception:
            return []

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{BASE_URL}/")
            return resp.status_code < 400
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
