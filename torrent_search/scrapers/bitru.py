"""BitRu.org torrent scraper (login required, forum tracker)."""

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

BASE_URL = SITE_URLS["bitru"]
LOGIN_PAGE = f"{BASE_URL}/forum/login.php"
SEARCH_URL = f"{BASE_URL}/forum/tracker.php"

USER_FIELDS = ("login_username", "username", "user", "login", "id")
PASS_FIELDS = ("login_password", "password", "pass", "passwd")


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


class BitRuScraper(BaseScraper):
    source = Source.BITRU

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._logged_in = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
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
            page = await client.get(LOGIN_PAGE)
            html = self._decode(page)
            if not _has_login_form(html):
                self._logged_in = True
                return True
            data, action = _login_payload(html, creds)
            post_url = _abs(BASE_URL, action or "forum/login.php")
            resp = await client.post(post_url, data=data)
            if resp.status_code >= 400:
                return False
            if client.cookies.get("bb_data"):
                self._logged_in = True
            else:
                self._logged_in = not _has_login_form(self._decode(resp))
        except Exception:
            return False
        return self._logged_in

    def _parse_results(self, html: str, category: str = "", base_url: str | None = None) -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("table.forumline") or soup.find("table")
        if not table:
            return []
        base = base_url or BASE_URL
        results = []
        for tr in table.find_all("tr"):
            link = tr.select_one("a[href*='viewtopic.php'], a.tLink, a.med")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            if not title:
                continue
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            href = link.get("href", "")
            page_url = _abs(base, href)
            cat = category
            if not cat and cells[0].find("img"):
                img = cells[0].find("img")
                cat = img.get("title") or img.get("alt") or ""
            size_idx = next(
                (i for i, td in enumerate(cells) if parse_size(td.get_text(" ", strip=True)) > 0),
                -1,
            )
            size_bytes = 0
            seeders = leechers = 0
            added = ""
            if size_idx >= 0:
                size_bytes = parse_size(cells[size_idx].get_text(" ", strip=True))
                if size_idx + 1 < len(cells):
                    seeders = _digits(cells[size_idx + 1].get_text(" ", strip=True))
                if size_idx + 2 < len(cells):
                    leechers = _digits(cells[size_idx + 2].get_text(" ", strip=True))
                added = cells[size_idx + 4].get_text(" ", strip=True) if size_idx + 4 < len(cells) else cells[-1].get_text(" ", strip=True)
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
        params = {"nm": query}
        category = kwargs.get("category")
        if category:
            if str(category).isdigit():
                params["f"] = str(category)
            elif "f" not in params:
                params["f"] = str(category)
        client = await self._get_client()
        try:
            resp = await client.get(f"{SEARCH_URL}?{urlencode(params)}")
            if resp.status_code in (403, 429, 503):
                return []
            resp.raise_for_status()
            return self._parse_results(self._decode(resp), kwargs.get("category", ""), str(resp.url))
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
