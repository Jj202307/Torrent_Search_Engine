"""Hand results to an external BitTorrent client (BiglyBT by default)."""

import asyncio
import hashlib
import shutil
import socket
import subprocess
import time
from urllib.parse import quote

import httpx

from .base import SearchResult
from .config import DEFAULT_USER_AGENT

# Name -> argv prefix used to open a URI in the client.
# NOTE: BiglyBT's flatpak ships a broken wrapper (/app/bin/biglybt-runner
# does `exec /app/biglybt/biglybt` WITHOUT "$@"), which drops every
# argument — magnets never reach the app, cold or warm. Bypassing the
# wrapper with --command delivers args to the real launcher script.
_CLIENT_LAUNCHERS: dict[str, list[str]] = {
    "biglybt": ["flatpak", "run", "--command=/app/biglybt/biglybt",
                "com.biglybt.BiglyBT"],
}

# Clients with a local control socket we can wait on after a cold launch.
# BiglyBT drops/mishandles argv passed while it is still booting, so we
# relaunch the URIs once its StartSocket (127.0.0.1:6880) accepts connections.
_READY_PROBES: dict[str, tuple[str, int]] = {
    "biglybt": ("127.0.0.1", 6880),
}


def resolve_client(name: str) -> list[str]:
    """Return the argv prefix that opens a URI in the named client."""
    name = (name or "biglybt").strip().lower()
    launcher = _CLIENT_LAUNCHERS.get(name)

    if launcher and launcher[0] == "flatpak":
        # argv like [flatpak, run, --command=..., APPID]: the app id is the
        # first token after "run" that isn't an option.
        app_id = next((t for t in launcher[2:] if not t.startswith("-")), None)
        try:
            ok = app_id is not None and subprocess.run(
                ["flatpak", "info", app_id],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
        except OSError:
            ok = False
        if not ok:
            launcher = None
    elif launcher:
        if shutil.which(launcher[0]) is None:
            launcher = None
    else:
        launcher = [name] if shutil.which(name) else None

    if not launcher:
        raise FileNotFoundError(
            f"Client {name!r} not found. BiglyBT is the default: "
            f"`flatpak run com.biglybt.BiglyBT` must be installed, "
            f"or pass --client pointing at a binary on PATH."
        )
    return launcher


def _skip_value(b: bytes, i: int) -> int:
    """Walk one bencode value starting at i, return index just past it."""
    c = b[i : i + 1]
    if c == b"d" or c == b"l":
        i += 1
        while b[i : i + 1] != b"e":
            if c == b"d":
                i = _skip_value(b, i)  # key
            i = _skip_value(b, i)
        return i + 1
    if c == b"i":
        return b.index(b"e", i) + 1
    j = b.index(b":", i)
    return j + 1 + int(b[i:j])


def _scan_torrent(b: bytes) -> tuple[int, int, list[bytes]]:
    """Locate the top-level info dict span and collect tracker URLs."""
    if not b.startswith(b"d"):
        raise ValueError("not a bencoded torrent")
    i, info_span, trackers = 1, None, []
    while b[i : i + 1] != b"e":
        j = b.index(b":", i)
        key, i = b[j + 1 : j + 1 + int(b[i : j])], j + 1 + int(b[i : j])
        start = i
        i = _skip_value(b, i)
        if key == b"info":
            info_span = (start, i)
        elif key == b"announce":
            m = b.index(b":", start)
            trackers.append(b[m + 1 : m + 1 + int(b[start:m])])
        elif key == b"announce-list":
            k = start
            while k < i:
                c = b[k : k + 1]
                if c in (b"l", b"e"):
                    k += 1
                else:  # length-prefixed tracker URL
                    m = b.index(b":", k)
                    ln = int(b[k:m])
                    trackers.append(b[m + 1 : m + 1 + ln])
                    k = m + 1 + ln
    if info_span is None:
        raise ValueError("no info dict")
    return info_span[0], info_span[1], trackers


def magnet_from_torrent(data: bytes, title: str) -> str:
    """Build a magnet URI from raw .torrent bytes (sha1 of the info dict)."""
    start, end, trackers = _scan_torrent(data)
    info_hash = hashlib.sha1(data[start:end]).hexdigest()
    params = [f"xt=urn:btih:{info_hash}", f"dn={quote(title)}"]
    seen = set()
    for t in trackers:
        if t not in seen:
            seen.add(t)
            params.append(f"tr={quote(t.decode('utf-8', 'replace'), safe='')}")
    return "magnet:?" + "&".join(params)


async def ensure_magnet(r: SearchResult) -> bool:
    """Populate r.magnet by fetching its .torrent (info hash + trackers).

    The .torrent mirrors are flaky under bursts (throttling, truncated or
    HTML bodies), so retry with backoff and only accept payloads that
    actually parse as bencoded torrents.
    """
    if r.magnet or not r.torrent_url:
        return bool(r.magnet)
    if "rutracker.org" in r.torrent_url:
        # dl.php needs the Cloudflare-cleared Firefox session — the
        # generic HTTP fetch below cannot reach it.
        from .scrapers.rutracker import fetch_torrent_magnet
        r.magnet = await fetch_torrent_magnet(r.title, r.torrent_url)
        if r.magnet:
            r.info_hash = r.magnet.split("btih:", 1)[1].split("&", 1)[0]
            return True
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            ) as client:
                resp = await client.get(r.torrent_url)
            resp.raise_for_status()
            if not resp.content[:1] == b"d":
                raise ValueError("not a bencoded torrent")
            r.magnet = magnet_from_torrent(resp.content, r.title)
            return True
        except Exception:
            await asyncio.sleep(0.8 * (attempt + 1))
    return False


def result_uri(r: SearchResult) -> str:
    """Best download seed for a result: magnet, torrent URL, or hash-built magnet."""
    if r.magnet:
        return r.magnet
    if r.torrent_url:
        return r.torrent_url
    if r.info_hash:
        return f"magnet:?xt=urn:btih:{r.info_hash}"
    return ""


def open_uri(launcher: list[str], uri: str) -> None:
    """Ask the client to add the URI. Never blocks on the client's lifetime."""
    subprocess.Popen(
        [*launcher, uri],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _listener_up(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


async def _await_listener(host: str, port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _listener_up(host, port):
            return True
        await asyncio.sleep(0.5)
    return False


async def download_results(results: list[SearchResult], client: str = "biglybt") -> list[dict]:
    """Send every result's URI to the client. Returns a per-result report."""
    launcher = resolve_client(client)
    report = []
    uris: list[str] = []
    for r in results:
        await ensure_magnet(r)
        uri = result_uri(r)
        if uri:
            uris.append(uri)
            report.append({"title": r.title, "status": "sent",
                           "via": "magnet" if r.magnet else "url"})
        else:
            report.append({"title": r.title, "status": "skip"})
    if not uris:
        return report

    name = (client or "biglybt").strip().lower()
    probe = _READY_PROBES.get(name)
    if probe is not None and not _listener_up(*probe):
        # Cold start: launch one URI to boot the client, wait for its
        # control socket, then send everything again — args handed over
        # mid-boot can be dropped, and duplicate adds are deduped by the
        # client itself.
        open_uri(launcher, uris[0])
        await _await_listener(*probe)
        for uri in uris:
            open_uri(launcher, uri)
            await asyncio.sleep(0.25)
        return report

    for uri in uris:
        open_uri(launcher, uri)
        await asyncio.sleep(0.25)
    return report


def print_download_summary(report: list[dict], client: str) -> None:
    sent = [r for r in report if r["status"] == "sent"]
    skipped = [r for r in report if r["status"] == "skip"]
    if sent:
        print(f"Opened {len(sent)} result(s) in {client}:")
        for r in sent:
            suffix = "  (direct URL — magnet conversion failed)" if r.get("via") == "url" else ""
            print(f"  {r['title'][:90]}{suffix}")
    if skipped:
        print(f"Skipped {len(skipped)} result(s) with no magnet/torrent link:")
        for r in skipped:
            print(f"  {r['title'][:90]}")
