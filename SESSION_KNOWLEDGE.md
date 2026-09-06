# Session Knowledge — Torrent Site Research & Build Log

Session date: 2026-08-01

## What this project is

A multi-source torrent search engine (CLI + Python package) with parallel async scrapers, a client-side filter engine for HD/4K/HQ/FLAC etc., and a common result schema. Built at user request to query free, no-subscription, no-invite BitTorrent sites, sorted by size/seeders, filtered by quality.

## Research findings (torrent sites, ranked by ~torrent count)

Verified count: **RuTracker = 2.7M torrents** (Wikipedia, May 2026). All others are self-reported estimates — no authoritative central database exists.

| ~Count | Site | Access |
|---|---|---|
| ~8M | The Pirate Bay | free, no account |
| 2.7M | RuTracker.org | free, optional signup |
| ~2.2M | YggTorrent | free, mandatory open signup |
| ~1.5M | 1337x | free, optional signup |
| ~1.3M | Nyaa.si | free (removed per user request) |
| ~1.2M | LimeTorrents | free |
| ~1.2M | Zamunda.net | free signup |
| ~1M | Maxitorrent.net | free signup |
| ~1M | Pornolab.net | free (removed) |
| ~1M | TorrentGalaxy | free (uptime unstable) |
| ~1M | AnimeTosho | free (removed) |
| ~0.5M | EXT.to | free, magnet indexer |
| ~0.4M | EZTVx.to | free, TV only |
| ~0.3M | Torrenting.com | free |
| ~0.2M | TorLock | free |
| ~0.15M | YTS.bz | free, movies only |
| ~0.15M | GimmePeers (ex-Demonoid) | free signup |
| ~0.12M | GloTorrents (glodls.to) | free (down, 521) |
| ~0.12M | BitRu | free signup |
| ~0.1M | Katcr.co | free |
| — | TorrentParadise | DHT meta-search |
| — | TorrentFunk | defunct |
| — | 7torrents | defunct |
| — | Torrents.io | defunct |
| — | Demonoid | low activity |
| — | TorrentDownloads | defunct |

Sites removed by user from the final list: Nyaa.si (#5), Pornolab.net (#9), AnimeTosho (#11), Skidrowreloaded (#21), FitGirl Repacks (#22), idope.se (#24), BTDB (#25).

Excluded by criteria (paid/invite-only): IPTorrents, AnimeBytes, TorrentLeech.

## Verified live domains (checked via fetch during session)

- thepiratebay.org — reachable; API at apibay.org works
- yts.bz — live; **API base moved to `https://movies-api.accel.li/api/v2`** (yts.bz/api/v2 now 301-redirects)
- limetorrents.lol — live
- torlock.com — live, clean 7-column table
- ext.to — live, Cloudflare-walled
- eztvx.to — live (403 on robots)
- zamunda.net — live (403 on robots)
- maxitorrent.net — live
- gimmepeers.com — serves revott.me login page
- katcr.co — robots disallow all
- yggtorrent.ws — live, domain rotates periodically
- glodls.to — 521 (Cloudflare down) at check time
- torrentgalaxy.to — connection failed at check time (likely down)

## Tooling analysis (how to query each site programmatically)

### JSON APIs (no scraping)
- **TPB**: `https://apibay.org/q.php?q={query}&cat={cat}` → JSON array with `id, name, info_hash, leechers, seeders, size(bytes), num_files, username, added(unix), status, category, imdb`. Only category filter server-side; everything else client-side. Tools: curl+jq, httpx, `torrentp`.
- **YTS**: `https://movies-api.accel.li/api/v2/list_movies.json` → params `query_term, quality(720p/1080p/2160p/3D), genre, sort_by(seeds/date/download_count), minimum_rating, page, limit`. Each movie has `torrents[]` with `quality, size, seeds, peers, hash, url`. **No magnet in API** — generate from hash. Server-side filters: quality, genre, min rating, sort. Tools: plain requests/httpx.

### HTML scrape (httpx + BeautifulSoup4/lxml)
- 1337x: `/search/{query}/1/`, `/category-search/{q}/{cat}/1/`, sort `/sort-{field}-{order}/`; rows in `table tbody tr`, cells `td.name`, `td.coll-2 seeds`, `td.coll-3 leeches`, `td.coll-4 size`. Libs: `py1337x`, `torrentp`.
- LimeTorrents: `/search/all/{query}/`, category path; parse `table.table2`, title from `td.tdleft`, size `td.tdnormal`, seeds/leeches `td.tdseed`/`td.tdleech`.
- TorLock: `/all/torrents/{query}.html`, category `.html` suffix; clean columns: name/size/seeds/peers. Easiest to parse.
- EZTVx: **RSS-first** `ezrss.xml?q={query}` (reliable), HTML fallback. `torrent:seeds/peers/size`, `<enclosure>` for magnet.
- EXT.to: `?q={query}`, magnet indexer, Cloudflare → needs browser TLS fingerprint (curl_cffi) or playwright/crawl4ai.
- Katcr: `katsearch.php?q={query}`, table parse.
- TorrentParadise: DHT meta-search, magnet link scan, seeds/leechers often 0.

### Login-required (free signup, no invites)
- RuTracker: POST `/forum/login.php`, cookie `bb_data`; search `/forum/tracker.php?nm={query}`; windows-1251 encoding. Lib: `rutracker-api`.
- YggTorrent: POST login, search `/engine/search?name={query}&category={id}` (2140 films, 2141 series, 2142 musique, 2143 jeux-video, 2144 applications, 2145 ebooks, 2146 animation); French units Go/Mo. Lib: `yggtorrentapi`.
- Zamunda, Maxitorrent, BitRu, GimmePeers: forum-style login + search, session cookie persistence.

### Shared stack
- Scraping: `requests`/`httpx` + `selectolax`/`BeautifulSoup4`; `curl_cffi`/`cloudscraper` for TLS fingerprint blocks; `playwright`/`crawl4ai` for Cloudflare.
- **Where HD/4K/HQ/FLAC filtering lives**: almost no public site supports these server-side. Implement a shared regex engine on normalized titles (`2160p|4k`, `1080p`, `720p`, `REMUX|WEB-DL|BLURAY`, `FLAC|ALAC|320`), plus min-seeders and size range.
- Agentic option: one subagent per site probing search/sort params → normalize to common schema → apply shared filter spec → return magnets.

## Architecture decisions

- Async throughout: `httpx.AsyncClient`, `asyncio.gather` for parallel site search.
- Common schema: `SearchResult` dataclass unifies all sources for consistent filtering/sorting.
- Graceful degradation: scraper failures return empty list, others continue.
- Client-side filtering: only TPB (category) and YTS (quality/genre/rating) support server-side filters.
- Login creds via `.env` (free-registration sites only).
- Persisted result index: every search saves its displayed results (numbered 1..N) to `.cache/sessions/last_results.json` via `state.py`, so `--download 1,3,4` works without re-querying.
- Client handoff: `download.py` opens each result's magnet in BiglyBT (`flatpak run com.biglybt.BiglyBT`, fallback `biglybt` binary, or any `--client` on PATH); missing magnets fall back to `torrent_url`, then a hash-built magnet.

## Bugs found & fixed during build

1. **YTS API moved**: old `yts.bz/api/v2` → 301. Fixed `config.py` `yts_api` → `https://movies-api.accel.li/api/v2`. Verified alive, returns torrents (seeders/peers/size/quality).
2. **FilterEngine `_check_pattern` case bug**: `pattern_dict.get(key.upper())` failed because dict keys are lowercase (`1080p` vs `1080P`). Fix: `pattern_dict.get(key) or pattern_dict.get(key.upper()) or pattern_dict.get(key.lower())`. Quality/codec filters were silently returning 0 results before this fix.
3. **Rich table clipping**: Seeders/Leechers columns appeared empty in bash-captured output — this was terminal-width capture clipping, not a code bug. Use `--format simple` for narrow terminals.

## Verification results (live, 2026-08-01)

- TPB `alive(): True`; "ubuntu" → 50 results, first = Ubuntu 22.04 LTS S:39 L:1 3.40 GB.
- YTS `alive(): True` (after API fix); "avatar" 1080p min-seeders 10 → 3 results (Way of Water S:100 L:41).
- All 16 scrapers import cleanly; CLI `--list-sources` shows all 16 ✓.
- Multi-source: `"debian" --sources tpb,yts` → combined filtered results.

## Key file map

```
torrent_search.sh        # launcher: hides `python3 -m ...`, onboarding, --install-aliases
torrent_search/
├── base.py        # SearchResult, Source(16 values), BaseScraper, ScraperResult
├── config.py      # SITE_URLS, CREDENTIALS, RATE_LIMITS, MAX_RESULTS_PER_SOURCE
├── filters.py     # FilterEngine (QUALITY/CODEC/SOURCE/HDR/CHANNEL/ENCODING patterns), FilterSpec
├── normalizer.py  # parse_size, parse_seeders_leechers, extract_magnet, extract_info_hash, to_int
├── state.py       # save_results/load_results: persisted numbered index (.cache/sessions/last_results.json)
├── download.py    # resolve_client/result_uri/download_results/print_download_summary → BiglyBT handoff
├── cli.py         # async CLI: search flags + --download SPEC/--show/--client/--no-hints, index column, hints block
└── scrapers/      # 16 scrapers, each with async search()/alive()/close(), Source set
```

## To run checks

```bash
cd ~/Downloads/Projects/Torrent_Search_Engine
python3 -c "from torrent_search import SearchResult, FilterEngine, FilterSpec; print('core OK')"
python3 -m torrent_search.cli --list-sources
python3 -m torrent_search.cli "avatar" --sources yts --quality 1080p --min-seeders 10 --format simple
# Download flow (after a search saves the index):
python3 -m torrent_search.cli --show
python3 -m torrent_search.cli --download 1,3-5 --client biglybt
# Convenience launcher:
./torrent_search.sh --install-aliases && source ~/.bashrc
torrent_search_dl --help
```

---

# Session 2026-09-06 — additions

## New sources added (16 → 19 scrapers)

| Site | Route | Result shape | Notes |
|---|---|---|---|
| yourbittorrent.com | `/?q={query}` | title `a.yb-tname` + `^/torrent/\d+/` relative href; size/added `td[data-label=…]`; seeders `td.sd`, peers `td.pr`; category `a.yb-cat[title]` | `.torrent` at `/down/{id}.torrent` (200, bencode). Same injected t0r.space spam rows as TorLock — filtered by the relative-href requirement. IP got 403-flagged after burst probing; block is server-side, may clear. |
| knaben.org | `/search/{query}` **path route** (the `?query=` form is a status-dashboard stub) | `tr` with `a[href^='magnet:']`; td[0] category, td[1] title+magnet, td[2] size, td[3] date, td[4] seeders, td[5] leechers, td[6] source site | Multi-tracker cached meta-search (aggregates TPB/YTS/etc). Magnet IS the row href; info_hash from btih. Best new general source. |
| audiobookbay.lu | `/?s={query}` (WordPress) | `div.post`; title `postTitle h2 a` → `/abss/{slug}/`; File Size regex over post div; magnet/hash on detail page | Detail pages publish `Info Hash:` + `/downld0?downfs=` link, no magnet anchor → scraper rebuilds magnet from hash. ~9 results/page, semaphore(4) detail fetches. TCP-unreachable from this network (geo); verified via relay. |
| snowfl.com | — | — | DROPPED: SPA with rotating-key JSON API; key vars no longer extractable from b.min.js. |

Registration touch points per new source: `base.py` Source enum, `config.py` SITE_URLS + RATE_LIMITS, `scrapers/<name>.py`, `scrapers/__init__.py`, `cli.py` `_scraper_modules`.

## Site liveness updates (2026-09-06)

- **Dead**: yts.mx (stopped Jan 2026 — scraper already on yts.bz + movies-api.accel.li, both live; yts.gg = current official gateway), torrentgalaxy.to (memecoin promo), glodls, zooqle.to, btdb.to, 7torrents, torrents.io, torrent.by, ilcorsaronero.info (hijacked), rarbg family (2023).
- **Robots-walled but alive** (policy call): torrent9.so, oxtorrent.co, cpasbien.run, btscene.cc, torrentproject2.net, katcr.co, animetosho.org (/search).
- **Cloudflare-walled**: rutracker.org (managed challenge; see below), ext.to, bitsearch.to, kickasstorrents.to, bt4g.
- **Verified live, not integrated**: rutor.info (`/search/{q}/0/0/0`, inline magnet+.torrent — best candidate), torrentfunk.com (+torrentfunk2.com mirror, `/all/torrents/{q}.html`), torrentdownloads.pro (`/search/?search={q}`).
- Note: yourbitorrent.com (dead) ≠ yourbittorrent.com (live).

## Bugs found & fixed (session 2)

4. **TorLock parser**: first-`<a>`-in-row picked the category link (or spam mirror link) as title; positional columns off by one; `torrent_url` was an HTML page (BiglyBT fetched HTML, silently dropped). Fix: `a.tl-name[href]` anchor, `td.ts/tul/tdl` classes, real `.torrent` at `lt.t0r.space/tor/{id}.torrent`.
5. **BiglyBT flatpak runner drops ALL CLI args** (root cause of "opens but nothing loads"): `/var/lib/flatpak/app/com.biglybt.BiglyBT/…/files/bin/biglybt-runner` is `exec /app/biglybt/biglybt` with no `"$@"`. Cold start booted argless; warm "StartSocket: passed startup args" message forwarded an EMPTY list. Fix in `download.py`: launch via `flatpak run --command=/app/biglybt/biglybt com.biglybt.BiglyBT` (main script forwards args correctly). Upstream flathub bug.
6. **Cold-start race**: client launched with a URI isn't ready to receive it. Fix in `download.py`: `_READY_PROBES` (127.0.0.1:6880), launch first URI → poll listener up to 60s → resend all URIs (client dedupes), 0.25s stagger.
7. **Magnet conversion flakiness** ("doesn't appear to be valid torrent file"): UA-less single-attempt fetch of `.torrent` mirrors failed under burst throttling → raw-URL fallback → BiglyBT fetched junk itself. Fix: `ensure_magnet` now sends DEFAULT_USER_AGENT, 3 attempts with backoff, bencode validation; summary marks `(direct URL — magnet conversion failed)` fallbacks.

## Download pipeline (as of session 2)

- `download.py` converts `.torrent` URLs to magnets client-side before handoff: fetch → bencode `_scan_torrent` (info-dict span + announce/announce-list trackers) → sha1 → `xt=urn:btih:` magnet with `dn`/`tr`. Hash verified against TPB's published magnet (e498d30e…). Needed because the BiglyBT flatpak sandbox can't fetch some mirrors and can't read `/tmp`.
- Alt clients: `--client qbittorrent` already works via PATH fallback; qBittorrent recommended if BiglyBT is dropped (magnet argv works cold+warm via single-instance IPC). ktorrent/rtorrent have handoff caveats.
- BiglyBT flatpak data: `~/.var/app/com.biglybt.BiglyBT/.biglybt/` (downloads.config, torrents/, logs/); stop with `flatpak kill com.biglybt.BiglyBT`.

## RuTracker status (open)

- Cloudflare managed challenge on login.php/tracker.php defeats httpx, curl_cffi, playwright chromium (headless+headed), patchright chromium/firefox headless. Firefox engine passes for the real user (their Brave loops — Brave farbling/fingerprint randomization is the culprit there; per-site fix: Shields → Block fingerprinting OFF).
- `.env` now has real creds (RUTRACKER_USERNAME/PASSWORD); `_login()` failure was the original silent-zero-results bug.
- Turnstile-click experiment script parked at `/tmp/opencode/rt_turnstile_click.py` (headed patchright firefox, clicks challenges.cloudflare.com iframe, saves storage state). Never run.
- Alternative once user passes CF manually in a real browser: harvest `bb_data` session cookie into the scraper's persistent session.

## Filter/CLI knowledge (4K aliases + ! negation — implemented 2026-09-06)

- All pattern filters (quality/codec/source-type/hdr) match `result.title` client-side; `QUALITY_PATTERNS['2160p']` already matches `2160p|4k|uhd`, `['1080p']` matches `1080p|fhd|full hd`. Only YTS has server-side quality (`QUALITY_MAP` incl. `4k`→`2160p`).
- `-q 4k` was an unknown key → filtered everything out. FIXED: `QUALITY_ALIASES` = {4k→2160p, uhd→2160p, fhd→1080p} in filters.py, resolved inside `_check_pattern` (case-insensitive, applied after stripping `!`).
- `-qx 480p` syntax impossible in argparse (value-taking `-q` swallows `x`). IMPLEMENTED instead: value negation `-q '!480p'` in `FilterEngine._check_pattern` — leading `!` marks an exclude (exclude wins over include; all-exclude list passes unless matched); keys unknown in the primary pattern dict fall back across the engine's other dicts; covers quality/codec/source-type/hdr uniformly. A `-x` argv preprocessor (~10 lines) was considered and rejected as stateful/fragile. `--must-not-contain` remains the raw-regex alternative.

## Pagination (added 2026-09-06)

- `--page N` (default 1) slices the merged → filtered → sorted list: rows `[(N-1)*limit : N*limit]`, with `--limit` as page size. Uniform across all 19 sources; the saved index (`last_results.json`) and `--download` numbering always match the displayed page.
- Deep pages (`--page > 1`) raise the per-source fetch cap via `config.set_max_results_per_source(page × limit)` — scrapers bind the constant at import time, so the helper patches each imported scraper module's global.
- Bound: per-source depth is limited to what the site's first results page serves (knaben ~50 rows → page 11 empty; TorLock pages carry more). Multi-source pools stack, so aggregate pages go deeper.
- Option B — true server-side per-site page params (1337x path page, YTS API `page`, rutracker `start`, yggtorrent `page`; knaben/torlock/yourbittorrent likely but unverified; TPB apibay and EZTVx RSS can't) — **deferred for later** per user (2026-09-06).
