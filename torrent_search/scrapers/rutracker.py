"""RuTracker.org torrent scraper (login + windows-1251).

rutracker.org sits behind a Cloudflare managed challenge that 403s every
plain HTTP client, and the forum needs a login. The working bypass:
harvest the cf_clearance + bb_session cookies from the user's local
Firefox profile (where the challenge was passed and the login done by
hand) and replay them through curl_cffi's Firefox TLS impersonation.
The session lives as long as the Firefox login does — if searches come
back empty, re-login on rutracker.org in Firefox.
"""

import glob
import os
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from ..base import BaseScraper, SearchResult, Source
from ..config import (
    SITE_URLS,
    DEFAULT_TIMEOUT,
    MAX_RESULTS_PER_SOURCE,
    CREDENTIALS,
)
from ..download import magnet_from_torrent
from ..normalizer import parse_size


async def fetch_torrent_magnet(title: str, torrent_url: str) -> str:
    """Fetch a rutracker .torrent via the Firefox-cookie session.

    dl.php sits behind the same Cloudflare clearance + login cookies as
    the forum, so it is unreachable for plain HTTP clients — the
    downloader must go through this path. Returns '' on any failure.
    """
    s = AsyncSession(
        impersonate="firefox135",
        timeout=DEFAULT_TIMEOUT,
        headers={
            "User-Agent": FIREFOX_UA,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
        cookies=_harvest_firefox_cookies(),
    )
    try:
        resp = await s.get(torrent_url)
        if resp.status_code != 200 or resp.content[:1] != b"d":
            return ""
        return magnet_from_torrent(resp.content, title)
    except Exception:
        return ""
    finally:
        await s.close()

BASE_URL = SITE_URLS["rutracker"]
LOGIN_PAGE = f"{BASE_URL}/forum/login.php"
SEARCH_URL = f"{BASE_URL}/forum/tracker.php"

CATEGORY_IDS = {
    "films": 2090,
    "movies": 2090,
    "series": 1930,
    "music": 100,
    "games": 900,
    "software": 1100,
    "apps": 1100,
    "books": 2000,
    "anime": 1000,
    "sport": 3300,
}
SORT_MAP = {"name": 1, "seeders": 2, "size": 3, "leechers": 4}

# Must match the browser the cookies were issued to (Firefox 153 ESR on
# this machine) — cf_clearance is bound to the User-Agent.
FIREFOX_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0"

USER_FIELDS = ("login_username", "username", "user", "login", "id")
PASS_FIELDS = ("login_password", "password", "pass", "passwd")


def _harvest_firefox_cookies() -> dict[str, str]:
    """Pull rutracker.org cookies from every local Firefox profile.

    The sqlite DBs are copied first — Firefox holds locks on the lives.
    """
    cookies: dict[str, str] = {}
    for db in glob.glob(os.path.expanduser("~/.mozilla/firefox/*/cookies.sqlite")):
        tmp = None
        try:
            tmp = tempfile.mkdtemp(prefix="ffck_")
            copy = os.path.join(tmp, "cookies.sqlite")
            shutil.copy2(db, copy)
            for ext in ("wal", "shm"):
                if os.path.exists(f"{db}-{ext}"):
                    shutil.copy2(f"{db}-{ext}", f"{copy}-{ext}")
            con = sqlite3.connect(copy)
            try:
                for name, value in con.execute(
                    "select name, value from moz_cookies"
                    " where host like '%rutracker.org'"
                ):
                    cookies[name] = value
            finally:
                con.close()
        except Exception:
            continue
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
    return cookies


def _decode(resp) -> str:
    ctype = resp.headers.get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ctype, re.IGNORECASE)
    enc = m.group(1) if m else "windows-1251"
    try:
        return resp.content.decode(enc, errors="replace")
    except LookupError:
        return resp.content.decode("windows-1251", errors="replace")


def _digits(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


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


class RuTrackerScraper(BaseScraper):
    source = Source.RUTRACKER

    def __init__(self):
        self._client: AsyncSession | None = None
        self._logged_in = False

    async def _get_client(self) -> AsyncSession:
        if self._client is None:
            self._client = AsyncSession(
                impersonate="firefox135",
                timeout=DEFAULT_TIMEOUT,
                headers={
                    "User-Agent": FIREFOX_UA,
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                },
                cookies=_harvest_firefox_cookies(),
            )
        return self._client

    async def _login(self) -> bool:
        if self._logged_in:
            return True
        creds = CREDENTIALS.get(self.source.value, {})
        client = await self._get_client()

        # Primary path: the Firefox-harvested session cookies. No probe
        # request — the search itself is the probe (one request total;
        # request volume is what burns the Cloudflare clearance).
        if client.cookies.get("cf_clearance") and client.cookies.get("bb_session"):
            self._logged_in = True
            return True

        # Legacy path: form login. Unusable while Cloudflare guards
        # login.php with a JS challenge, kept for a future without it.
        if not creds.get("username") or not creds.get("password"):
            return False
        try:
            page = await client.get(LOGIN_PAGE)
            html = _decode(page)
            if not _has_login_form(html):
                self._logged_in = True
                return True
            data, _ = _login_payload(html, creds)
            resp = await client.post(LOGIN_PAGE, data=data)
            if resp.status_code >= 400:
                return False
            self._logged_in = not _has_login_form(_decode(resp))
        except Exception:
            return False
        return self._logged_in

    def _build_url(self, query: str, **kwargs) -> str:
        params = {"nm": query}
        category = kwargs.get("category")
        if category:
            cid = CATEGORY_IDS.get(str(category).lower(), category if str(category).isdigit() else None)
            if cid:
                params["f"] = str(cid)
        sort = kwargs.get("sort")
        if sort:
            parts = str(sort).split(":")
            field = SORT_MAP.get(parts[0].lower())
            if field:
                params["s"] = str(field)
                params["o"] = "1" if len(parts) > 1 and parts[1].lower() == "asc" else "2"
        return f"{SEARCH_URL}?{urlencode(params)}"

    def _parse_results(self, html: str, base_url: str | None = None) -> list[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("table.forumline")
        if not table:
            return []
        base = base_url or BASE_URL
        results = []
        for tr in table.find_all("tr"):
            link = tr.select_one("a.tLink, a[href*='viewtopic.php?t=']")
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            if not title:
                continue
            cells = tr.find_all("td")
            href = link.get("href", "")
            page_url = urljoin(base, href)

            cat = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""
            size_bytes = 0
            size_td = tr.select_one("td.tor-size")
            if size_td is not None:
                ts = size_td.get("data-ts_text") or ""
                size_bytes = int(ts) if ts.isdigit() else parse_size(size_td.get_text(" ", strip=True))
            seeders = _digits(cells[6].get_text(" ", strip=True)) if len(cells) > 6 else 0
            leechers = _digits(cells[7].get_text(" ", strip=True)) if len(cells) > 7 else 0
            uploader = cells[4].get_text(" ", strip=True) if len(cells) > 4 else ""
            added = cells[9].get_text(" ", strip=True) if len(cells) > 9 else ""

            # The .torrent endpoint rides on the size link (dl.php?t=<id>)
            # and needs the authenticated session — see search().
            dl = tr.select_one("a.tr-dl[href]")
            torrent_url = urljoin(base, dl.get("href")) if dl else page_url

            results.append(SearchResult(
                title=title,
                source=self.source,
                category=cat,
                size_bytes=size_bytes,
                seeders=seeders,
                leechers=leechers,
                torrent_url=torrent_url,
                page_url=page_url,
                added=added,
                uploader=uploader,
            ))
            if len(results) >= MAX_RESULTS_PER_SOURCE:
                break
        return results

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        if not await self._login():
            return []
        client = await self._get_client()
        try:
            resp = await client.get(self._build_url(query, **kwargs))
            if resp.status_code in (403, 429, 503):
                return []
            resp.raise_for_status()
            return self._parse_results(_decode(resp), str(resp.url))
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
            await self._client.close()
            self._client = None
