"""Hand results to an external BitTorrent client (BiglyBT by default)."""

import shutil
import subprocess

from .base import SearchResult

# Name -> argv prefix used to open a URI in the client.
_CLIENT_LAUNCHERS: dict[str, list[str]] = {
    "biglybt": ["flatpak", "run", "com.biglybt.BiglyBT"],
}


def resolve_client(name: str) -> list[str]:
    """Return the argv prefix that opens a URI in the named client."""
    name = (name or "biglybt").strip().lower()
    launcher = _CLIENT_LAUNCHERS.get(name)

    if launcher and launcher[0] == "flatpak":
        try:
            ok = subprocess.run(
                ["flatpak", "info", launcher[2]],
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


def download_results(results: list[SearchResult], client: str = "biglybt") -> list[dict]:
    """Send every result's URI to the client. Returns a per-result report."""
    launcher = resolve_client(client)
    report = []
    for r in results:
        uri = result_uri(r)
        if not uri:
            report.append({"title": r.title, "status": "skip"})
            continue
        open_uri(launcher, uri)
        report.append({"title": r.title, "status": "sent"})
    return report


def print_download_summary(report: list[dict], client: str) -> None:
    sent = [r for r in report if r["status"] == "sent"]
    skipped = [r for r in report if r["status"] == "skip"]
    if sent:
        print(f"Opened {len(sent)} result(s) in {client}:")
        for r in sent:
            print(f"  {r['title'][:90]}")
    if skipped:
        print(f"Skipped {len(skipped)} result(s) with no magnet/torrent link:")
        for r in skipped:
            print(f"  {r['title'][:90]}")
