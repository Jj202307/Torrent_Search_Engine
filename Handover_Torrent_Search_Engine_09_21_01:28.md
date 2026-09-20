# Handover — Torrent_Search_Engine

First handover file for this repo. Session date: 2026-09-21. Refreshed later the same day, after the session's work was committed (2f3333b → 2a774a5 → cc0ca78, HEAD): replay-cache layer, deep-paging fix, runtime facts and timings below are current.

## Original Goal / End Goals

Make the torrent search CLI reliable against trackers hardened behind Cloudflare — rutracker.org (login + managed challenge) and ext.to — so `torrent_search_dl "<query>"` finds and downloads torrents end-to-end, with diagnostics that tell the truth about which layer broke.

Session intent, verbatim from the user's brief: "The production pipeline now works via FlareSolverr fallback, so raw 403 is EXPECTED." The earlier VPN-switching theory is disproven: from the same IP, the raw curl_cffi path gets 403 while the FlareSolverr path passes — the differentiator is the client fingerprint, not the egress IP. This session closed out that pivot by (1) reworking `--probe` around the real chain (Firefox cookies → FlareSolverr → parsed rows), (2) recording the session's work in a CHANGELOG, (3) writing this handover.

## Current State (verified facts)

### What works today
- **tpb search via apibay API** — measured this session: `./torrent_search.sh --sources tpb ubuntu --limit 3` → 3 rows, exit 0.
- **rutracker search (logged-in) + magnet extraction** — production-confirmed earlier this session: real search returned parsed rows; dl.php fetch through the same session produced a real infohash magnet.
- **rutracker chain end-to-end** — measured this session via the reworked probe: `./torrent_search.sh --probe` → harvest OK (bb_session + cf_clearance), egress 146.70.111.110 (AS9009 M247 Europe SRL, Belgrade), direct path CHALLENGED HTTP 403 (expected), FlareSolverr OK at `http://localhost:8191/v1`, verdict PASS — 58 result rows (via FlareSolverr), exit 0.
- **extto** — metadata-only as guest by design: browse-row parser yields title/size/seeders; magnet is intentionally empty (the guest magnet button is auth-gated AJAX).
- **rutracker deep paging** — fixed this session (cc0ca78, details under "Fixed"): `--rt-pages 2` (`-P 2`) → 100 rows, correct Cyrillic («июль 2026»), 7.3s for both pages.

### Fixed this session (commit cc0ca78)
- **Deep-paging silent truncation at page 1 + mojibake:** deep paging built fake response objects without headers → `_decode`'s `resp.headers.get()` raised AttributeError, swallowed by the `except-break`, so paging silently stopped after page 1. Compounding it, str pages re-encoded utf-8 were re-decoded as cp1251 (mojibake). Fix: declared `content-type: text/html; charset=utf-8` on all three fake responses; the rutracker replay path decodes via the existing `_decode` helper (windows-1251 default), so Cyrillic titles survive.

### Architecture decisions
- **FlareSolverr docker sidecar** (upstream image 3.5.2), host network, port :8191, persistent sessions `rutracker` and `extto`.
- **Why cookie-replay and browser engines failed:** Cloudflare hardening landed 2026-07-29 (cf. Jackett#16975, elementum-burst#501). CF actively rejects vanilla curl_cffi impersonation, patchright and camoufox; cookies harvested from a real browser do NOT transfer on the raw path (verified locally + burst#501). `torrent_search/browser_fallback.py` is that superseded engine-based fallback, kept selectable via `BROWSER_FALLBACK_ENGINE` with kill switch `RUTRACKER_BROWSER_FALLBACK=0`.
- **The chrome136 replay recipe (the one that works):** FlareSolverr solves the challenge in its own Chrome (`returnOnlyCookies`, session-scoped); the solver's `cf_clearance` + its own User-Agent are then replayed through curl_cffi impersonating **chrome136**, so TLS fingerprint, UA and cookies all match the clearance. Firefox-harvested `bb_session`/`bb_ssl`/`bb_guid` login cookies are injected into the FS session; `cf_clearance` is deliberately excluded there (UA-bound to Firefox while FS runs Chrome).
- **Replay cache layer (commit cc0ca78):** FS solve happens once per host; the successful solve's `{cookies, user_agent}` persist to `~/.cache/torrent_search/fs_replay_<host>.json` (0600 perms, atomic mkstemp→os.replace). Repeat requests replay the cached clearance via chrome136 (~1-2s) instead of re-solving (30-60s), until CF re-challenges. Invalidation is failure-driven only: 403/429/503, challenge markers, or unparseable rows → entry cleared → fresh FS solve → cache re-saved. No TTL. Shared helpers in `flaresolverr.py`: `load_replay_cache` / `save_replay_cache` / `clear_replay_cache` / `replay_get` (text) / `replay_get_bytes` (binary). Wired into the rutracker search fast-path (before the direct attempt) + deep-paging pages + `_fs_replay_bytes` + `_fetch_via_flaresolverr`, and the extto search fast-path (browse URL with Referer).
- **`torrent_search/probe.py`** verifies the chain in production order: cookie harvest (bb_session required) → egress IP (informational) → FlareSolverr health (`sessions.list` against the client's URL) → real FS search verdict for `tracker.php?nm=ubuntu` via the scraper's own `_fetch_via_flaresolverr` (no second implementation). The raw direct request is demoted to an informational line and never affects the exit code. Exit 0 = chain OK; 1 = broken layer named with its fix; 2 = unknown source.

### Runtime prerequisites
1. VPN up (current egress: M247 Europe SRL, Belgrade — any exit works; CF judges the client, not the IP).
2. Docker container `flaresolverr` running: `docker start flaresolverr`.
3. Fresh Firefox cookies: user logged into rutracker.org in (snap) Firefox. Harvest covers native/snap/flatpak Firefox + Opera (PBKDF2 AES decrypt).

### Runtime facts & measured timings (2026-09-21, post-commit)
- **Commits (today):** `2f3333b` FlareSolverr integration (client, rutracker/extto wiring, cookie harvesting, `--probe`, UA auto-detect, deps fixes, docs consolidation: changelog.md merged into CHANGELOG.md, handover.md bannered SUPERSEDED) → `2a774a5` `*.egg-info/` gitignored, build artifacts untracked → `cc0ca78` persistent replay cache + deep-paging fix (HEAD).
- **FlareSolverr sidecar:** docker container `flaresolverr`, host network, port :8191, API at `/v1`, persistent sessions `rutracker` and `extto`. VPN required (torrenting policy).
- **Replay-cache dir:** `~/.cache/torrent_search/` (`fs_replay_<host>.json` per host).
- Measured same day, live (warm = cached replay, cold = fresh FS solve):

| Path | Warm | Cold |
|---|---|---|
| rutracker search | 1.3s | 62.3s (~47×) |
| extto search | 1.8s | 14.8s |
| .torrent magnet fetch | 1.3s | 30.5s |

- Robustness check: a corrupted-cache run still returned 5 rows via clean FS re-solve + re-save.

### Credentials
`.env` at the repo root holds `RUTRACKER_USERNAME` / `RUTRACKER_PASSWORD`, loaded by `config.py` via python-dotenv. Values intentionally not copied here. Note: the form-login path is dead while CF guards login.php — the harvested cookies do the login.

### Known gaps
- extto guest = metadata-only by design (magnet empty — the guest magnet button is auth-gated AJAX); downloads impossible as guest. A logged-in ext.to flow would need the rutracker-style cookie-harvest treatment.
- `cf_clearance` is excluded from FS injection (UA-bound to Firefox while FS runs Chrome) — each FS session must earn its own clearance, which is exactly what the replay cache makes cheap.
- FS solve time scales with IP suspicion: 61s observed worst-case (ecosystem-normal for FlareSolverr); warm replays are ~1-2s.
- Direct curl_cffi path is permanently challenged (HTTP 403) — expected steady state; FlareSolverr is the sanctioned solve path.
- `config.py` `FLARESOLVERR_URL` default (`http://localhost:8191/api/v3`) is stale and unused; the client (`flaresolverr.py`) uses `http://localhost:8191/v1`. The probe checks the client's URL.

### Verification commands
```
./torrent_search.sh --sources rutracker ubuntu --limit 5
./torrent_search.sh --probe
./torrent_search.sh --sources tpb ubuntu --limit 3
```

### Git state (refreshed post-commit, 2026-09-21)
- All session work is committed: **2f3333b** → **2a774a5** → **cc0ca78** (HEAD, cc0ca78 = "1"). `torrent_search_engine.egg-info/` is gitignored and untracked (2a774a5).

## Done vs Pending

Done (mapped to goals):
- Reliable rutracker access via FlareSolverr fallback in search + dl.php magnet fetch → serves end goal 1 (measured: 58 rows via FS, real infohash earlier in session).
- Honest diagnostics: probe reworked around the real chain; VPN-switching advice removed from docstring and output → serves end goal 2 (measured: exit 0, PASS).
- Session record: `CHANGELOG.md` created (Added/Fixed/Changed under `[Unreleased]`) → serves end goal 3.
- Replay-cache speedup (cc0ca78): warm rutracker search 1.3s vs 62.3s cold solve (~47×); extto 1.8s vs 14.8s; magnet fetch 1.3s vs 30.5s; corrupted cache self-heals via fresh solve.
- Deep-paging truncation + mojibake fixed (cc0ca78): `--rt-pages 2` → 100 rows, Cyrillic intact.
- Everything committed (2f3333b, 2a774a5, cc0ca78); egg-info gitignored.

Pending:
- Decide fate of `config.py`'s stale `FLARESOLVERR_URL` default (align to `/v1` or delete the dead constant).

## Exact Next Steps
1. If rutracker searches come back empty later: run `./torrent_search.sh --probe` — it names the broken layer and the fix (re-login Firefox / `docker start flaresolverr` / `docker logs flaresolverr`). Suspect the replay cache only if rows come back unparseable — it self-clears on failure and re-solves.
2. Only if extto metadata-only stops being enough: wire a logged-in ext.to cookie harvest analogous to rutracker's.

## Rules / Constraints Honored
- No commits during the original 01:28 session window (explicit user instruction); the work was committed later the same day (2f3333b → 2a774a5 → cc0ca78). This docs refresh is itself commit-free.
- `.venv/bin/python` used for all runs (not `uv run` — wrong interpreter version).
- Probe reuses the scraper's existing FlareSolverr fetch path — no second implementation invented.
- No secrets, tokens or credential values in this handover or the changelog.
