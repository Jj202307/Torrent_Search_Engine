"""RuTracker.org torrent scraper (login + windows-1251).

rutracker.org sits behind a Cloudflare managed challenge that 403s every
plain HTTP client, and the forum needs a login. The working bypass:
harvest the cf_clearance + bb_session cookies from the user's local
Firefox profile (where the challenge was passed and the login done by
hand) and replay them through curl_cffi's Firefox TLS impersonation.
The session lives as long as the Firefox login does — if searches come
back empty, re-login on rutracker.org in Firefox.
"""

import asyncio
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
    "games": 900,
    "software": 1100,
    "apps": 1100,
    "books": 2000,
    "anime": 1000,
    "sport": 3300,
}
SORT_MAP = {"name": 1, "seeders": 2, "size": 3, "leechers": 4}

# Server paging constants: tracker.php serves PAGE_SIZE rows per page;
# deeper pages ride a per-query search_id token (start=N*50). The server
# hard-caps every query at 500 rows, so MAX_PAGES=10 is exhaustive.
PAGE_SIZE = 50
PAGE_DELAY = 5.0   # seconds between page fetches — bursts burn the CF clearance
MAX_PAGES = 10

# Named forum presets (server-side scope narrowing via repeated f= params).
# Preset keys are what the user types; labels are what humans read.
FORUM_PRESETS: dict[str, dict] = {
    "hi-res": {
        "label": "Hi-Res (lossless stereo/multichannel music)",
        "forums": [1163, 1164, 1396, 1397, 1755, 1757, 1884, 1885,
                   1890, 1893, 2302, 2303, 2345, 2346, 2512, 2513],
    },
    "digitizations": {
        "label": "Digitization (rips of analog media)",
        "forums": [123, 239, 450, 506, 974, 1217, 1444, 1625,
                   1660, 1754, 1756, 1758, 1766, 1835, 2301, 2401],
    },
}
FORUM_PRESETS["dsd"] = {
    "label": "DSD everywhere (Hi-Res + Digitization)",
    "forums": sorted(set(FORUM_PRESETS["hi-res"]["forums"])
                     | set(FORUM_PRESETS["digitizations"]["forums"])),
}
FORUM_PRESETS["movies"] = {
    "label": "Movies (foreign & Russian cinema, DVD/HD/UHD, cartoons, anime, theater, 3D)",
    # Branch ids (7, 22, 124, 93, 2198, 718, 33) AND their leaves —
    # tracker.php?f= is NOT recursive (verified live 2026-09-06: parent
    # scope returns only the parent's own topics), so leaves are required.
    "forums": [4, 7, 22, 33, 93, 124, 2198, 352, 511, 718, 921,
               100, 101, 187, 252, 271, 312, 313, 572, 941, 1105, 1106,
               1457, 1543, 1577, 1666, 1940, 1950, 2200, 2339],
}
FORUM_PRESETS["tv-series"] = {
    "label": "TV Series (Russian, foreign, Latin American/Turkish/Indian, Asian)",
    # f=26 is a discussion forum (0 torrent rows, verified live) — excluded.
    "forums": [9, 32, 81, 91, 812, 920,
               189, 842, 119, 242, 721, 819, 1102, 1117, 1120, 1171, 1214,
               1359, 1417, 1531, 1803, 2366,
               911, 704, 781, 823, 1301, 1493, 1539, 1574, 1606,
               2100, 717, 915, 1242, 1938, 2102, 2103, 2104, 2412],
}

# Full directory of selectable forums with descriptive names, grouped by
# branch (verified via viewforum pages; service forums excluded). Drives
# --rt-list-forums so raw ids never have to be memorized.
FORUM_DIRECTORY: list[tuple[str, list[tuple[int, str]]]] = [
    ("Hi-Res — branch 1299 (Hi-Res stereo и многоканальная музыка)", [
        (1163, "Dolby Atmos"),
        (1164, "Classical vocal / Crossover"),
        (1396, "Alt / Punk / Indie"),
        (1397, "Soundtracks"),
        (1755, "Rock"),
        (1757, "Prog / Art Rock"),
        (1884, "Classical instrumental"),
        (1885, "Pop"),
        (1890, "Metal"),
        (1893, "Electronic"),
        (2302, "Jazz (Cool / Fusion / Avant-Garde)"),
        (2303, "Vocal Jazz / Funk / Soul / R&B"),
        (2345, "Blues"),
        (2346, "Bop"),
        (2512, "Other genres"),
        (2513, "New Age / Relax / Flamenco"),
    ]),
    ("Digitization — branch 2219 (Оцифровки с аналоговых носителей)", [
        (123, "Alt / Punk / Indie"),
        (239, "Russian pop"),
        (450, "Instrumental pop"),
        (506, "Folk / ethno"),
        (974, "Other genres"),
        (1217, "Chanson / military"),
        (1444, "Foreign pop"),
        (1625, "Soundtracks / musicals"),
        (1660, "Classical"),
        (1754, "Electronic"),
        (1756, "Foreign rock"),
        (1758, "Russian rock"),
        (1766, "Metal"),
        (1835, "Rap / Hip-Hop / Reggae / Ska / Dub"),
        (2301, "Jazz / blues"),
        (2401, "Soviet estrada / retro"),
    ]),
    ("Movies — branch 7 (Foreign Cinema)", [
        (7, "Foreign Cinema — all (branch)"),
        (187, "World cinema classics"),
        (2200, "Films 2016-2020"),
        (1950, "Films 2021-2025"),
        (252, "Films 2026"),
    ]),
    ("Movies — branch 22 (Russian Cinema)", [
        (22, "Russian Cinema — all (branch)"),
        (941, "Soviet cinema"),
        (1666, "Children's domestic films"),
    ]),
    ("Movies — branch 124 (Art-house & Auteur)", [
        (124, "Art-house — all (branch)"),
        (1543, "Short films"),
        (1577, "Animation (art-house)"),
    ]),
    ("Movies — branch 93 (DVD Video)", [
        (93, "DVD Video — all (branch)"),
        (101, "Foreign DVD"),
        (100, "Russian DVD"),
        (572, "Art-house DVD"),
    ]),
    ("Movies — branch 2198 (HD Video)", [
        (2198, "HD Video — all (branch)"),
        (313, "Foreign HD"),
        (312, "Russian HD"),
        (2339, "Art-house HD"),
    ]),
    ("Movies — branch 718 (UHD Video)", [
        (718, "UHD Video — all (branch)"),
        (1457, "Foreign UHD"),
        (1940, "Russian UHD"),
        (271, "Art-house UHD"),
    ]),
    ("Movies — standalone forums", [
        (4, "Cartoons"),
        (921, "Animated series"),
        (33, "Anime — all (branch)"),
        (1106, "Ongoing anime (HD)"),
        (1105, "Anime (HD)"),
        (511, "Theater"),
        (352, "3D / stereoscopic cinema"),
    ]),
    ("TV Series — branch 9 (Russian)", [
        (9, "Russian series — all (branch)"),
        (32, "Old Russian series"),
        (81, "Russian series (HD)"),
        (812, "Russian series (UHD)"),
        (920, "Russian series (DVD)"),
        (91, "Russian series (DVD, legacy)"),
    ]),
    ("TV Series — branch 189 (Foreign)", [
        (189, "Foreign series — all (branch)"),
        (842, "New & currently airing"),
        (1803, "New shows (HD)"),
        (2366, "Foreign series (HD)"),
        (119, "Foreign series (UHD)"),
        (1171, "New shows (UHD)"),
        (1417, "Foreign series (DVD)"),
        (242, "UK & Irish"),
        (819, "Scandinavian"),
        (1531, "Spanish"),
        (721, "Italian"),
        (1102, "European"),
        (1120, "African & Middle Eastern"),
        (1117, "Canadian"),
        (1359, "Japanese"),
        (1214, "Multi-country co-productions"),
    ]),
    ("TV Series — branch 911 (Latin America / Turkey / India)", [
        (911, "Branch — all"),
        (1493, "Argentine"),
        (1301, "Brazilian"),
        (704, "Venezuelan"),
        (1574, "Indian"),
        (1539, "Colombian"),
        (823, "Mexican"),
        (1606, "Turkish"),
        (781, "Portuguese"),
    ]),
    ("TV Series — branch 2100 (Asian)", [
        (2100, "Asian series — all (branch)"),
        (717, "Chinese"),
        (915, "Japanese"),
        (1242, "Thai"),
        (2412, "Vietnamese"),
        (1938, "Taiwanese"),
        (2104, "Indonesian"),
        (2102, "Philippine"),
        (2103, "Malaysian"),
    ]),
]

FORUM_NAMES: dict[int, str] = {
    fid: name for _, forums in FORUM_DIRECTORY for fid, name in forums
}

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


def _torrent_id(page_url: str) -> str:
    """Stable dedupe key for a row: the topic id (t=...) in its URL."""
    m = re.search(r"[?&]t=(\d+)", page_url or "")
    return m.group(1) if m else (page_url or "")


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
        """Build a tracker.php URL.

        Params are kept as a list of tuples so repeated f= entries
        urlencode into forum filters (rutracker ANDs them). An empty
        query yields browse mode (f= only, no nm=).
        """
        params: list[tuple[str, str]] = []
        if query and query.strip():
            params.append(("nm", query))

        forums: list[int] = list(kwargs.get("forums") or [])
        category = kwargs.get("category")
        if category:
            preset = FORUM_PRESETS.get(str(category).lower())
            if preset:
                forums.extend(preset["forums"])
            else:
                cid = CATEGORY_IDS.get(str(category).lower(),
                                       category if str(category).isdigit() else None)
                if cid:
                    forums.append(int(cid))
        for fid in forums:
            params.append(("f", str(fid)))

        sort = kwargs.get("sort")
        if sort:
            parts = str(sort).split(":")
            field = SORT_MAP.get(parts[0].lower())
            if field:
                params.append(("s", str(field)))
                params.append(("o", "1" if len(parts) > 1 and parts[1].lower() == "asc" else "2"))
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
        pages = max(1, min(int(kwargs.get("pages") or 1), MAX_PAGES))
        merged: list[SearchResult] = []
        seen: set[str] = set()
        try:
            resp = await client.get(self._build_url(query, **kwargs))
            if resp.status_code in (403, 429, 503):
                return []
            resp.raise_for_status()
            html = _decode(resp)
            for r in self._parse_results(html, str(resp.url)):
                key = _torrent_id(r.page_url)
                if key not in seen:
                    seen.add(key)
                    merged.append(r)

            # Deep paging: tracker.php?search_id=<token>&start=N*50. The
            # token comes from the first response's own pagination links.
            token = re.search(r"search_id=([\w-]{6,})", html)
            for n in range(1, pages):
                if token is None or len(merged) < n * PAGE_SIZE:
                    break  # no token (single page) or previous page was short
                await asyncio.sleep(PAGE_DELAY)
                resp = await client.get(
                    f"{SEARCH_URL}?search_id={token.group(1)}&start={n * PAGE_SIZE}"
                )
                if resp.status_code in (403, 429, 503):
                    break  # keep whatever was collected
                resp.raise_for_status()
                new = [r for r in self._parse_results(_decode(resp), str(resp.url))
                       if _torrent_id(r.page_url) not in seen]
                if not new:
                    break
                for r in new:
                    seen.add(_torrent_id(r.page_url))
                merged.extend(new)
            return merged
        except Exception:
            return merged

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
