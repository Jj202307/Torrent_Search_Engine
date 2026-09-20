"""RuTracker.org torrent scraper (login + windows-1251).

rutracker.org sits behind a Cloudflare managed challenge that 403s every
plain HTTP client, and the forum needs a login. The working bypass:
harvest the cf_clearance + bb_session cookies from the user's local
Firefox/Opera profiles (where the challenge was passed and the login
done by hand) and replay them through curl_cffi's Firefox TLS
impersonation.
The session lives as long as the Firefox login does — if searches come
back empty, re-login on rutracker.org in Firefox.
"""

import asyncio
import glob
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    Cipher = algorithms = modes = None

from ..base import BaseScraper, SearchResult, Source
from ..config import (
    SITE_URLS,
    DEFAULT_TIMEOUT,
    MAX_RESULTS_PER_SOURCE,
    CREDENTIALS,
)
from ..download import magnet_from_torrent
from ..flaresolverr import solve_url as flaresolverr_solve
from ..normalizer import parse_size

logger = logging.getLogger(__name__)


async def fetch_torrent_magnet(title: str, torrent_url: str) -> str:
    """Fetch a rutracker .torrent via the Firefox-cookie session.

    dl.php sits behind the same Cloudflare clearance + login cookies as
    the forum, so it is unreachable for plain HTTP clients — the
    downloader must go through this path. First try replays the
    Firefox-harvested cookies through curl_cffi's Firefox TLS
    impersonation; when CF still 403s, falls back to a FlareSolverr
    solve + Chrome-family replay. Returns '' on any failure.
    """
    # dl.php lives under /forum/ — repair URLs the parser joined against
    # the bare site root (e.g. https://rutracker.org/dl.php?t=N).
    if "dl.php" in torrent_url and "/forum/" not in torrent_url:
        torrent_url = urljoin(
            BASE_URL + "/", "forum/" + torrent_url.rsplit("/", 1)[-1]
        )
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
        if resp.status_code == 200 and resp.content[:1] == b"d":
            return magnet_from_torrent(resp.content, title)
    except Exception:
        pass
    finally:
        await s.close()

    content = await _fs_replay_bytes(torrent_url)
    if content:
        return magnet_from_torrent(content, title)
    return ""

BASE_URL = SITE_URLS["rutracker"]
LOGIN_PAGE = f"{BASE_URL}/forum/login.php"
SEARCH_URL = f"{BASE_URL}/forum/tracker.php"


async def _fs_replay_bytes(url: str) -> bytes | None:
    """Fetch a CF-guarded URL by FlareSolverr solve + Chrome replay.

    FS solves the challenge for its own persistent Chrome session
    (cookies only — no HTML needed); the target URL is then replayed
    via curl_cffi impersonating the SOLVER's Chrome family so TLS
    fingerprint, User-Agent and cookies all match the clearance
    (standard working pattern, cf. jacred). Returns the raw body bytes
    on success, None on any failure.
    """
    fs = await flaresolverr_solve(
        BASE_URL + "/forum/index.php",
        session_id="rutracker",
        return_only_cookies=True,
    )
    if not fs or not fs.get("cookies"):
        return None
    s = AsyncSession(
        impersonate="chrome136",
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": fs.get("userAgent", "")},
        cookies={
            c["name"]: c["value"] for c in fs["cookies"] if c.get("name")
        },
    )
    try:
        resp = await s.get(url)
        if resp.status_code == 200 and resp.content[:1] == b"d":
            return resp.content
    except Exception:
        pass
    finally:
        await s.close()
    return None

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

# Cloudflare challenge markers in the response body (Russian).
_CHALLENGE_MARKERS = ("Один момент", "challenges.cloudflare.com")

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
    # Rebuilt from the LIVE branch tree (walk 2026-09-06, 241 forums):
    # tracker.php?f= is NOT recursive, so every content leaf is enumerated.
    # Service / discussion / archive / "некондиционные" forums excluded.
    "forums": [
               4, 7, 22, 33, 84, 93, 100, 101, 106, 124, 140, 149, 166, 181,
               185, 187, 194, 208, 209, 212, 252, 254, 271, 272, 312, 313, 352,
               376, 404, 484, 498, 505, 511, 514, 521, 539, 549, 572, 599, 653,
               709, 718, 771, 772, 775, 789, 809, 815, 816, 822, 877, 905, 921,
               930, 934, 941, 1105, 1106, 1213, 1235, 1247, 1277, 1386, 1387,
               1389, 1390, 1391, 1454, 1457, 1460, 1493, 1543, 1576, 1577, 1640,
               1642, 1666, 1670, 1692, 1900, 1940, 1950, 2090, 2091, 2092, 2093,
               2097, 2109, 2183, 2198, 2199, 2200, 2201, 2220, 2221, 2258, 2339,
               2343, 2365, 2373, 2374, 2459, 2484, 2491, 2540, 2544
    ],
}
FORUM_PRESETS["tv-series"] = {
    "label": "TV Series (Russian, foreign SD/HD/UHD, US & Canada, LatAm/Turkey/India, Asian)",
    # Rebuilt from the LIVE branch tree (walk 2026-09-06): rutracker RECYCLES
    # dead ids — 32/1117/823/1606/1938/2103/2104 now dead-or-repurposed, 1493
    # moved to Theater. US & Canada (235/266/1669) + all HD/UHD leaves added.
    "forums": [
               9, 79, 80, 81, 91, 104, 110, 119, 121, 173, 175, 184, 188, 189,
               193, 235, 242, 265, 266, 325, 372, 387, 489, 504, 507, 534, 536,
               594, 607, 625, 694, 704, 717, 721, 781, 812, 819, 820, 825, 842,
               911, 915, 920, 990, 1102, 1120, 1144, 1171, 1214, 1242, 1248,
               1288, 1301, 1359, 1408, 1417, 1449, 1459, 1463, 1531, 1535, 1539,
               1574, 1669, 1690, 1803, 1939, 1949, 2100, 2102, 2366, 2370, 2393,
               2396, 2398, 2404, 2405, 2412
    ],
}

# Full directory of selectable forums with descriptive names, rebuilt from
# the LIVE branch tree (2026-09-06 walk; service forums excluded; labels
# translated from live Russian titles, show forums keep familiar names).
# Drives --rt-list-forums so raw ids never have to be memorized.
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
    ("TV Series — branch 9 (Russian)", [
        (9, "Russian series — all (branch)"),
        (79, "Ugly Girlfriend"),
        (80, "Rural Detective"),
        (81, "Russian series (HD)"),
        (91, "I Know Your Secrets"),
        (104, "Психология преступления"),
        (175, "Sled (The Trail)"),
        (188, "Moscow Mysteries"),
        (812, "Russian series (UHD)"),
        (920, "Russian series (DVD)"),
        (990, "Univer / Sashatanya"),
        (1408, "Female Version"),
        (1535, "Wartime-law detective"),
    ]),
    ("TV Series — branch 189 (Foreign, SD)", [
        (110, "Секретные материалы / The X-Files"),
        (121, "Твин пикс / Twin Peaks"),
        (184, "Бесстыжие / Shameless (US)"),
        (189, "Foreign series — all (branch)"),
        (235, "US & Canada (SD)"),
        (242, "UK & Ireland (SD)"),
        (372, "Сверхъестественное / Supernatural"),
        (387, "Multi-country co-pro (SD)"),
        (489, "Ex-USSR (SD)"),
        (504, "Клан Сопрано / The Sopranos"),
        (507, "Теория большого взрыва + Детство Шелдона"),
        (536, "Форс-мажоры / Костюмы в законе / Suits"),
        (721, "Italian (SD)"),
        (819, "Scandinavian (SD)"),
        (842, "New & airing"),
        (1102, "European (SD)"),
        (1120, "Africa & Middle East (SD)"),
        (1144, "Ходячие мертвецы + Бойтесь ходячих мертвецов"),
        (1214, "Australia & NZ (SD)"),
        (1359, "Web series & pilots"),
        (1417, "Во все тяжкие / Breaking Bad"),
        (1449, "Игра престолов / Game of Thrones"),
        (1531, "Spanish (SD)"),
    ]),
    ("TV Series — branch 2366 (Foreign, HD)", [
        (193, "UK & Ireland (HD)"),
        (265, "Игра престолов / Game of Thrones (HD)"),
        (266, "US & Canada (HD)"),
        (825, "Australia & NZ (HD)"),
        (1248, "Ex-USSR (HD)"),
        (1288, "Multi-country co-pro (HD)"),
        (1459, "European (HD)"),
        (1463, "Africa & Middle East (HD)"),
        (1690, "Scandinavian (HD)"),
        (1803, "New & airing (HD)"),
        (2366, "Foreign series (HD) — all (branch)"),
        (2370, "Твин пикс / Twin Peaks (HD)"),
        (2396, "Теория Большого Взрыва / The Big Bang Theory (HD)"),
        (2398, "Ходячие мертвецы + Бойтесь ходячих мертвецов (HD)"),
        (2404, "Сверхъестественное / Supernatural (HD)"),
        (2405, "Секретные материалы / The X-Files (HD)"),
    ]),
    ("TV Series — branch 119 (Foreign, UHD)", [
        (119, "Foreign series (UHD) — all (branch)"),
        (173, "Multi-country co-pro (UHD)"),
        (625, "European (UHD)"),
        (1171, "New & airing (UHD)"),
        (1669, "US & Canada (UHD)"),
        (1949, "Australia & NZ (UHD)"),
        (2393, "UK & Ireland (UHD)"),
    ]),
    ("TV Series — branch 911 (Latin America / Turkey / India)", [
        (325, "Argentine"),
        (534, "Brazilian"),
        (594, "Venezuelan"),
        (607, "Colombian"),
        (694, "Mexican"),
        (704, "Turkish"),
        (781, "Multi-country co-pro (SD)"),
        (911, "Сериалы Латинской Америки, Турции и Индии"),
        (1301, "Indian"),
        (1539, "LatAm subtitled"),
        (1574, "LatAm dubbed (folder dumps)"),
    ]),
    ("TV Series — branch 2100 (Asian)", [
        (717, "Chinese"),
        (820, "Asian series (UHD)"),
        (915, "Korean (SD)"),
        (1242, "Korean (HD)"),
        (1939, "Japanese"),
        (2100, "Asian series — all (branch)"),
        (2102, "Asian clips & shorts"),
        (2412, "Thailand/Indonesia/Singapore"),
    ]),
    ("Movies — branch 7 (Foreign Cinema)", [
        (7, "Foreign cinema — all (branch)"),
        (166, "Foreign films untranslated"),
        (185, "Audio tracks & translations"),
        (187, "World cinema classics"),
        (212, "Film collections"),
        (252, "Films 2026"),
        (254, "Foreign actors — filmographies"),
        (505, "Indian cinema"),
        (771, "Foreign directors"),
        (934, "Asian cinema"),
        (1235, "Grindhouse"),
        (1454, "Fan (author) translations"),
        (1640, "Curated link collections"),
        (1692, "Translator teams"),
        (1950, "Films 2021-2025"),
        (2090, "Films pre-1990"),
        (2091, "Films 2001-2005"),
        (2092, "Films 2006-2010"),
        (2093, "Films 2011-2015"),
        (2200, "Films 2016-2020"),
        (2221, "Films 1991-2000"),
        (2373, "Pro dubbing/voiceover studios"),
        (2374, "Voiceover releases"),
        (2459, "Short films"),
        (2540, "Ex-USSR films"),
    ]),
    ("Movies — branch 22 (Russian Cinema)", [
        (22, "Russian cinema — all (branch)"),
        (106, "RU/USSR films in national languages"),
        (376, "Directorial debuts"),
        (772, "Russian/Soviet directors"),
        (789, "Russian/Soviet actors — filmographies"),
        (941, "Soviet cinema"),
        (1666, "Children's domestic films"),
    ]),
    ("Movies — branch 93 (DVD Video)", [
        (93, "DVD Video"),
        (100, "Russian cinema (DVD)"),
        (101, "Foreign cinema (DVD)"),
        (572, "Art-house (DVD)"),
        (877, "Ex-USSR films (DVD)"),
        (905, "World cinema classics (DVD)"),
        (1576, "Asian cinema (DVD)"),
        (1670, "Grindhouse (DVD)"),
        (2220, "Indian cinema (DVD)"),
    ]),
    ("Movies — branch 2198 (HD Video)", [
        (140, "Indian cinema (HD)"),
        (194, "Grindhouse (HD)"),
        (312, "Russian cinema (HD)"),
        (313, "Foreign cinema (HD)"),
        (653, "Анонсы (U)HD Video"),
        (1247, "Ex-USSR films (HD)"),
        (2198, "HD Video"),
        (2199, "World cinema classics (HD)"),
        (2201, "Asian cinema (HD)"),
        (2339, "Art-house (HD)"),
    ]),
    ("Movies — branch 718 (UHD Video)", [
        (271, "Art-house (UHD)"),
        (272, "Asian cinema (UHD)"),
        (718, "UHD Video"),
        (775, "World cinema classics (UHD)"),
        (1457, "Foreign cinema (UHD)"),
        (1940, "Russian cinema (UHD)"),
    ]),
    ("Movies — branch 124 (Art-house & Auteur)", [
        (124, "Art-house & auteur — all (branch)"),
        (149, "Filmographies (auteur)"),
        (709, "Documentary (art-house)"),
        (1543, "Short films"),
        (1577, "Animation (art-house)"),
    ]),
    ("Movies — standalone (cartoons / anime / theater / 3D)", [
        (4, "Cartoons"),
        (33, "Anime — all (branch)"),
        (84, "Cartoons (UHD)"),
        (181, "Cartoons untranslated"),
        (208, "Domestic cartoons"),
        (209, "Foreign cartoons"),
        (352, "3D cinema/TV/sport — all (branch)"),
        (404, "Покемоны"),
        (484, "Foreign cartoon shorts"),
        (498, "Animated series (UHD)"),
        (511, "Theater"),
        (514, "3D Sport"),
        (521, "Иностранные мультфильмы (DVD)"),
        (539, "Domestic feature cartoons"),
        (549, "3D movies"),
        (599, "Anime (DVD)"),
        (809, "Audio tracks & translations (anime)"),
        (815, "Animated series (SD)"),
        (816, "Animated series (DVD)"),
        (822, "Cartoon collections"),
        (921, "Animated series"),
        (930, "Foreign cartoons (HD)"),
        (1105, "Anime (HD)"),
        (1106, "Ongoing anime (HD)"),
        (1213, "3D cartoons"),
        (1277, "Donghua & ani"),
        (1386, "Anime art & scans"),
        (1387, "AMV & clips"),
        (1389, "Anime (SD)"),
        (1390, "Naruto"),
        (1391, "Anime player subforum"),
        (1460, "Animated series (HD)"),
        (1493, "Theater — untranslated stagings"),
        (1642, "Gundam"),
        (1900, "Отечественные мультфильмы (DVD)"),
        (2097, "3D clips & trailers"),
        (2109, "3D documentaries"),
        (2183, "Ex-USSR cartoons"),
        (2258, "Иностранные короткометражные мультфильмы (DVD)"),
        (2343, "Domestic cartoons (HD)"),
        (2365, "Foreign cartoon shorts (HD)"),
        (2484, "Anime artbooks & magazines"),
        (2491, "Anime QC subforum"),
        (2544, "One Piece"),
    ]),
]

FORUM_NAMES: dict[int, str] = {
    fid: name for _, forums in FORUM_DIRECTORY for fid, name in forums
}

# cf_clearance is bound to the User-Agent, so this must match the browser
# the cookies were issued to. Firefox (especially the snap) auto-updates,
# so the version is detected from the installed browser at import time;
# the constant is only a fallback when no firefox binary is found.
_FIREFOX_UA_FALLBACK = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"
)


def _detect_firefox_ua() -> str:
    """User-Agent of the locally installed Firefox, detected at import."""
    for cmd in ("firefox --version", "flatpak run org.mozilla.firefox --version"):
        try:
            out = subprocess.run(
                cmd.split(), capture_output=True, text=True, timeout=10
            ).stdout
        except Exception:
            continue
        m = re.search(r"rv:(\d+)", out)
        if m:
            return (
                f"Mozilla/5.0 (X11; Linux x86_64; rv:{m.group(1)}.0) "
                f"Gecko/20100101 Firefox/{m.group(1)}.0"
            )
    return _FIREFOX_UA_FALLBACK


FIREFOX_UA = _detect_firefox_ua()

USER_FIELDS = ("login_username", "username", "user", "login", "id")
PASS_FIELDS = ("login_password", "password", "pass", "passwd")


def _cookie_db_candidates() -> list[str]:
    """Every Firefox/Opera cookie DB present, across packaging variants.

    Firefox (native, snap, flatpak) keeps one sqlite per profile with a
    plaintext ``value`` column. Opera (native, snap) keeps a single
    Chrome-format ``Cookies`` file whose ``encrypted_value`` holds
    v10/v11 blobs. Deduped, deterministic order; later DBs overwrite
    same-named cookies.
    """
    patterns = (
        "~/.mozilla/firefox/*/cookies.sqlite",
        "~/snap/firefox/common/.mozilla/firefox/*/cookies.sqlite",
        "~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/cookies.sqlite",
        "~/.config/opera/Cookies",
        "~/.config/opera/*/Cookies",
        "~/snap/opera/common/.config/opera/Cookies",
        "~/snap/opera/*/**/.config/opera*/Cookies",
    )
    seen: set[str] = set()
    found: list[str] = []
    for pat in patterns:
        for db in sorted(glob.glob(os.path.expanduser(pat), recursive=True)):
            if db not in seen:
                seen.add(db)
                found.append(db)
    return found


def _decrypt_opera_cookie(blob: bytes) -> str:
    """AES-128-CBC decrypt a Chrome-on-Linux v10/v11 cookie blob."""
    key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, dklen=16)
    if blob[:3] in (b"v10", b"v11"):
        blob = blob[3:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    padded = decryptor.update(blob) + decryptor.finalize()
    pad = padded[-1]
    if 1 <= pad <= 16:
        padded = padded[:-pad]
    return padded.decode("utf-8", errors="replace")


def _harvest_opera_db(con: sqlite3.Connection, cookies: dict[str, str]) -> None:
    """Merge rutracker cookies from one Chrome-format ``Cookies`` file."""
    if Cipher is None:
        logger.warning(
            "cryptography not installed — Opera cookie DB skipped"
            " (declared dependency; restore with: uv pip install"
            " -r requirements.txt)"
        )
        return
    rows = list(con.execute(
        "select name, value, encrypted_value from cookies"
        " where host_key like '%rutracker.org'"
    ))
    if not rows:
        return
    got: dict[str, str] = {}
    failures = 0
    for name, value, enc in rows:
        if value:
            got[name] = value
            continue
        if not enc:
            continue
        try:
            dec = _decrypt_opera_cookie(enc)
        except Exception:
            failures += 1
            continue
        if dec and dec.isprintable():
            got[name] = dec
        else:
            failures += 1
    if failures and not got:
        # Expected on modern Opera (keyring-encrypted v11 cookies) — not an
        # error: the Firefox session is the operative one. Debug-level so it
        # doesn't read like a login problem.
        logger.debug(
            "Opera cookie DB skipped: %d cookie(s) keyring-encrypted"
            " (v11) — Firefox profile covers the session", failures
        )
        return
    cookies.update(got)


def _harvest_firefox_cookies() -> dict[str, str]:
    """Pull rutracker.org cookies from every local Firefox/Opera profile.

    Covers native, snap and flatpak installs on Ubuntu/openSUSE. The
    sqlite DBs are copied first — the browsers hold locks on the live
    ones. Firefox values are plaintext; Opera (Chrome format) values
    are decrypted with the stock Linux key when possible.
    """
    cookies: dict[str, str] = {}
    for db in _cookie_db_candidates():
        tmp = None
        try:
            tmp = tempfile.mkdtemp(prefix="ffck_")
            copy = os.path.join(tmp, os.path.basename(db))
            shutil.copy2(db, copy)
            for ext in ("wal", "shm"):
                if os.path.exists(f"{db}-{ext}"):
                    shutil.copy2(f"{db}-{ext}", f"{copy}-{ext}")
            con = sqlite3.connect(copy)
            try:
                if os.path.basename(db) == "Cookies":
                    _harvest_opera_db(con, cookies)
                else:
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
        search_url = self._build_url(query, **kwargs)

        # Primary path: curl_cffi (fast, no sidecar dependency).
        # Fall back to FlareSolverr when challenged.
        resp = await client.get(search_url)
        if resp.status_code in (403, 429, 503):
            logger.warning(
                "rutracker: Cloudflare challenge (HTTP %s) — trying FlareSolverr",
                resp.status_code,
            )
            html = await self._fetch_via_flaresolverr(query, kwargs)
            if not html:
                return []
        else:
            resp.raise_for_status()
            html = _decode(resp)

        if self._is_challenge(html):
            logger.warning("rutracker: JS challenge detected — trying FlareSolverr")
            html = await self._fetch_via_flaresolverr(query, kwargs)
        if not html:
            return []

        for r in self._parse_results(html, None):
            key = _torrent_id(r.page_url)
            if key not in seen:
                seen.add(key)
                merged.append(r)

        # Deep paging: tracker.php?search_id=<token>&start=N*50.
        token = re.search(r"search_id=([\w-]{6,})", html)
        for n in range(1, pages):
            if token is None or len(merged) < n * PAGE_SIZE:
                break
            await asyncio.sleep(PAGE_DELAY)
            try:
                if self._use_flaresolverr(html):
                    resp_html = await self._fetch_via_flaresolverr(
                        query, kwargs, search_id=token.group(1), start=n * PAGE_SIZE
                    )
                    if not resp_html:
                        break
                    resp = type("_R", (), {"url": search_url, "content": resp_html.encode()})()
                else:
                    resp = await client.get(
                        f"{SEARCH_URL}?search_id={token.group(1)}&start={n * PAGE_SIZE}"
                    )
                    if resp.status_code in (403, 429, 503):
                        resp_html = await self._fetch_via_flaresolverr(
                            query, kwargs, search_id=token.group(1), start=n * PAGE_SIZE
                        )
                        if not resp_html:
                            break
                        resp = type("_R", (), {"url": search_url, "content": resp_html.encode()})()
                    else:
                        resp.raise_for_status()
                        resp = type("_R", (), {
                            "url": resp.url,
                            "content": resp.content,
                            "headers": resp.headers,
                        })()
            except Exception:
                break
            new = [r for r in self._parse_results(_decode(resp), str(resp.url))
                   if _torrent_id(r.page_url) not in seen]
            if not new:
                break
            for r in new:
                seen.add(_torrent_id(r.page_url))
            merged.extend(new)
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

    @staticmethod
    def _is_challenge(html: str) -> bool:
        """Return True when the HTML body looks like a JS challenge page."""
        if not html:
            return False
        return any(m in html for m in _CHALLENGE_MARKERS)

    @staticmethod
    def _use_flaresolverr(html: str) -> bool:
        """Decide whether deep-paging should also ride FlareSolverr.

        Once the first page was solved by FS, every subsequent page
        likely needs the same treatment (same cleared session).
        """
        return bool(html and any(m in html for m in _CHALLENGE_MARKERS))

    async def _fetch_via_flaresolverr(
        self,
        query: str,
        kwargs: dict,
        search_id: str | None = None,
        start: int | None = None,
    ) -> str | None:
        """Fetch a search page through FlareSolverr and return raw HTML."""
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
        if search_id:
            params.append(("search_id", search_id))
        if start is not None:
            params.append(("start", str(start)))

        url = f"{SEARCH_URL}?{urlencode(params)}"

        # Feed the harvested login session into FS's Chrome (cf_clearance
        # excluded — it is UA-bound to Firefox and would poison the
        # FlareSolverr session).
        harvested = _harvest_firefox_cookies()
        fs_cookies = [
            {"name": n, "value": v, "domain": ".rutracker.org", "path": "/forum/"}
            for n, v in harvested.items()
            if n in ("bb_session", "bb_ssl", "bb_guid") and v
        ]
        if not fs_cookies:
            logger.warning(
                "rutracker: no login cookies harvested — FlareSolverr will"
                " fetch as guest; search requires login"
            )

        result = await flaresolverr_solve(
            url, session_id="rutracker", cookies=fs_cookies or None
        )
        if result and result.get("html"):
            return result["html"]
        return None
