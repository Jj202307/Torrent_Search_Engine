"""GimmePeers.com (revott.me) torrent scraper (login required)."""

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
from ..normalizer import extract_magnet, parse_size

BASE_URL = SITE_URLS["gimmepeers"]

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


class GimmePeersScraper(BaseScraper):
    source = Source.GIMMEPEERS

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._logged_in = False
        self._base = BASE_URL

    def _update_base(self, url: str):
        m = re.match(r"(https?://[^/]+)", url)
        if m:
            self._base = m.group(1)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": DEFAULT_USER_AGENT},
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
            page = await client.get(f"{self._base}/ucp.php?mode=login")
            self._update_base(str(page.url))
            html = self._decode(page)
            if not _has_login_form(html):
                self._logged_in = True
                return True
            data, action = _login_payload(html, creds)
            post_url = _abs(self._base, action or "ucp.php?mode=login")
            resp = await client.post(post_url, data=data)
            self._update_base(str(resp.url))
            if resp.status_code >= 400:
                return False
            self._logged_in = not _has_login_form(self._decode(resp))
        except Exception:
            return False
        return self._logged_in

    def _parse_results(self, html: str, category: str = "", base_url: str | None = None) -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        base = base_url or self._base
        results = []
        seen = set()
        for link in soup.select("a[href*='viewtopic.php']"):
            title = link.get_text(" ", strip=True)
            href = link.get("href", "")
            if not title or href in seen or len(title) < 4 or title.isdigit():
                continue
            seen.add(href)
            page_url = _abs(base, href)
            magnet = extract_magnet(link.get("href", ""))
            results.append(SearchResult(
                title=title,
                source=self.source,
                category=category,
                size_bytes=parse_size(link.get_text(" ", strip=True)),
                torrent_url=page_url,
                page_url=page_url,
                magnet=magnet,
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
        return results

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        if not await self._login():
            return []
        client = await self._get_client()
        candidates = [
            f"{self._base}/search.php?{urlencode({'keywords': query, 'sr': 'topics', 'terms': 'all'})}",
            f"{self._base}/?{urlencode({'q': query})}",
        ]
        for url in candidates:
            try:
                resp = await client.get(url)
                self._update_base(str(resp.url))
                if resp.status_code in (403, 429, 503):
                    continue
                resp.raise_for_status()
                results = self._parse_results(self._decode(resp), kwargs.get("category", ""), str(resp.url))
                if results:
                    return results
            except Exception:
                continue
        return []

    async def alive(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base}/")
            return resp.status_code < 400
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
