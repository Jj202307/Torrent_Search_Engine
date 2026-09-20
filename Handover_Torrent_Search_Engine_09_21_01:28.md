# Handover — Torrent_Search_Engine

First handover file for this repo. Session date: 2026-09-21.

## Original Goal / End Goals

Make the torrent search CLI reliable against trackers hardened behind Cloudflare — rutracker.org (login + managed challenge) and ext.to — so `torrent_search_dl "<query>"` finds and downloads torrents end-to-end, with diagnostics that tell the truth about which layer broke.

Session intent, verbatim from the user's brief: "The production pipeline now works via FlareSolverr fallback, so raw 403 is EXPECTED." The earlier VPN-switching theory is disproven: from the same IP, the raw curl_cffi path gets 403 while the FlareSolverr path passes — the differentiator is the client fingerprint, not the egress IP. This session closed out that pivot by (1) reworking `--probe` around the real chain (Firefox cookies → FlareSolverr → parsed rows), (2) recording the session's work in a CHANGELOG, (3) writing this handover.

## Current State (verified facts)

### What works today
- **tpb search via apibay API** — measured this session: `./torrent_search.sh --sources tpb ubuntu --limit 3` → 3 rows, exit 0.
- **rutracker search (logged-in) + magnet extraction** — production-confirmed earlier this session: real search returned parsed rows; dl.php fetch through the same session produced a real infohash magnet.
- **rutracker chain end-to-end** — measured this session via the reworked probe: `./torrent_search.sh --probe` → harvest OK (bb_session + cf_clearance), egress 146.70.111.110 (AS9009 M247 Europe SRL, Belgrade), direct path CHALLENGED HTTP 403 (expected), FlareSolverr OK at `http://localhost:8191/v1`, verdict PASS — 58 result rows (via FlareSolverr), exit 0.
- **extto** — metadata-only as guest by design: browse-row parser yields title/size/seeders; magnet is intentionally empty (the guest magnet button is auth-gated AJAX).

### Architecture decisions
- **FlareSolverr docker sidecar** (upstream image 3.5.2), host network, port :8191, persistent sessions `rutracker` and `extto`.
- **Why cookie-replay and browser engines failed:** Cloudflare hardening landed 2026-07-29 (cf. Jackett#16975, elementum-burst#501). CF actively rejects vanilla curl_cffi impersonation, patchright and camoufox; cookies harvested from a real browser do NOT transfer on the raw path (verified locally + burst#501). `torrent_search/browser_fallback.py` is that superseded engine-based fallback, kept selectable via `BROWSER_FALLBACK_ENGINE` with kill switch `RUTRACKER_BROWSER_FALLBACK=0`.
- **The chrome136 replay recipe (the one that works):** FlareSolverr solves the challenge in its own Chrome (`returnOnlyCookies`, session-scoped); the solver's `cf_clearance` + its own User-Agent are then replayed through curl_cffi impersonating **chrome136**, so TLS fingerprint, UA and cookies all match the clearance. Firefox-harvested `bb_session`/`bb_ssl`/`bb_guid` login cookies are injected into the FS session; `cf_clearance` is deliberately excluded there (UA-bound to Firefox while FS runs Chrome).
- **`torrent_search/probe.py`** verifies the chain in production order: cookie harvest (bb_session required) → egress IP (informational) → FlareSolverr health (`sessions.list` against the client's URL) → real FS search verdict for `tracker.php?nm=ubuntu` via the scraper's own `_fetch_via_flaresolverr` (no second implementation). The raw direct request is demoted to an informational line and never affects the exit code. Exit 0 = chain OK; 1 = broken layer named with its fix; 2 = unknown source.

### Runtime prerequisites
1. VPN up (current egress: M247 Europe SRL, Belgrade — any exit works; CF judges the client, not the IP).
2. Docker container `flaresolverr` running: `docker start flaresolverr`.
3. Fresh Firefox cookies: user logged into rutracker.org in (snap) Firefox. Harvest covers native/snap/flatpak Firefox + Opera (PBKDF2 AES decrypt).

### Credentials
`.env` at the repo root holds `RUTRACKER_USERNAME` / `RUTRACKER_PASSWORD`, loaded by `config.py` via python-dotenv. Values intentionally not copied here. Note: the form-login path is dead while CF guards login.php — the harvested cookies do the login.

### Known gaps
- extto guest downloads are impossible by design (auth-gated AJAX magnet button); a logged-in ext.to flow would need the rutracker-style cookie-harvest treatment.
- Direct curl_cffi path is permanently challenged (HTTP 403) — expected steady state; FlareSolverr is the sanctioned solve path.
- `config.py` `FLARESOLVERR_URL` default (`http://localhost:8191/api/v3`) is stale and unused; the client (`flaresolverr.py`) uses `http://localhost:8191/v1`. The probe checks the client's URL.

### Verification commands
```
./torrent_search.sh --sources rutracker ubuntu --limit 5
./torrent_search.sh --probe
./torrent_search.sh --sources tpb ubuntu --limit 3
```

### Git state (nothing committed this session)
- Modified (6): `pyproject.toml`, `requirements.txt`, `torrent_search/cli.py`, `torrent_search/config.py`, `torrent_search/scrapers/extto.py`, `torrent_search/scrapers/rutracker.py`
- Untracked: `torrent_search/flaresolverr.py`, `torrent_search/browser_fallback.py`, `torrent_search/probe.py`, plus `CHANGELOG.md`, this handover, `uv.lock`, `torrent_search_engine.egg-info/`

## Done vs Pending

Done (mapped to goals):
- Reliable rutracker access via FlareSolverr fallback in search + dl.php magnet fetch → serves end goal 1 (measured: 58 rows via FS, real infohash earlier in session).
- Honest diagnostics: probe reworked around the real chain; VPN-switching advice removed from docstring and output → serves end goal 2 (measured: exit 0, PASS).
- Session record: `CHANGELOG.md` created (Added/Fixed/Changed under `[Unreleased]`) → serves end goal 3.

Pending:
- Commit the session's work — user explicitly ordered no commits this session; left for the user / next session.
- Decide fate of `config.py`'s stale `FLARESOLVERR_URL` default (align to `/v1` or delete the dead constant).
- `torrent_search_engine.egg-info/` should be gitignored before committing.

## Exact Next Steps
1. Review the diff of the 6 modified files; stage everything relevant (including `flaresolverr.py`, `browser_fallback.py`, `probe.py`, `CHANGELOG.md`, handover) and commit — do not stage `torrent_search_engine.egg-info/`.
2. If rutracker searches come back empty later: run `./torrent_search.sh --probe` — it names the broken layer and the fix (re-login Firefox / `docker start flaresolverr` / `docker logs flaresolverr`).
3. Only if extto metadata-only stops being enough: wire a logged-in ext.to cookie harvest analogous to rutracker's.

## Rules / Constraints Honored
- No commits (explicit user instruction for this session).
- `.venv/bin/python` used for all runs (not `uv run` — wrong interpreter version).
- Probe reuses the scraper's existing FlareSolverr fetch path — no second implementation invented.
- No secrets, tokens or credential values in this handover or the changelog.
