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

## RuTracker status (WORKING — Firefox cookie bridge, 2026-09-06)

### Required user actions for rutracker to work

1. **Be logged into rutracker.org in the local Firefox** (free account; one-time). The CLI harvests `bb_session` + `cf_clearance` (+bb_guid/bb_ssl) from `~/.mozilla/firefox/*/cookies.sqlite` before every run — the `RUTRACKER_*` entries in `.env` are NOT used for login (the legacy form-login path in rutracker.py is kept but unusable while CF guards login.php).
2. **Pass the Cloudflare check IN FIREFOX**: open `https://rutracker.org/forum/tracker.php?nm=test` in Firefox. If the "Verify you are human" checkbox appears, **click it** and wait for the results page to load. Only a checkbox-click-solved clearance is replayable by the CLI; a page that loads by itself (invisible auto-rotate) does NOT mint a replayable clearance.
3. **Then use the CLI normally**: `torrent_search_dl "dune" -s rutracker`.
4. **When rutracker returns empty again** → repeat action 2 (open the tracker URL in Firefox, click the box if it appears, wait for results) and re-run the search.
5. **Keep volume light**: 1 request per search, +1 per `--download`ed rutracker result (its `.torrent` fetch). Bursts re-trigger the challenge and burn the replayed clearance.
6. **After a Firefox upgrade**: bump `FIREFOX_UA` in `torrent_search/scrapers/rutracker.py` to the new version — `cf_clearance` is bound to the User-Agent string.

### How the bypass works

- Harvest: `_harvest_firefox_cookies()` copies each `~/.mozilla/firefox/*/cookies.sqlite` (+wal/shm) to a temp dir (live DBs are locked) and reads `moz_cookies WHERE host LIKE '%rutracker.org'`. All four cookies are never-expiring.
- Replay: `curl_cffi` `AsyncSession(impersonate="firefox135")` with UA `…Firefox/153.0` (must match the cookie-issuing browser). `_login()` = both cookies present → logged_in, zero probe requests; the search itself is the probe.
- **Critical: request volume burns the clearance.** A 50-fetch burst (magnet conversion for all results at search time) made CF re-challenge the replay client; invisible auto-rotated clearances do NOT replay. A **checkbox-solved** clearance (user clicks verification manually in Firefox) replays fine. Search is now exactly 1 request (`tracker.php`); magnets are fetched only per downloaded torrent.
- Forum index is NOT CF-guarded; only login.php/tracker.php/dl.php are.
- Parser: 10-td rows — td2 category, td3 title (`a.tLink`), td4 uploader, td5 `td.tor-size` (`data-ts_text` = exact bytes; contains `a.tr-dl` → `dl.php?t=<id>` .torrent link), td6 seeders, td7 leechers, td9 added. windows-1251. `fetch_torrent_magnet()` (module-level) fetches dl.php through a fresh cookie session; `download.ensure_magnet` routes `rutracker.org` URLs to it (plain httpx can't reach dl.php).
- Dead ends proven: httpx/curl_cffi direct (403), playwright+patchright chromium any mode, patchright firefox headless+headed (challenge starts, never completes), turnstile-iframe click (widget iframe never renders under automation), real Firefox binary headless via Marionette (`navigator.webdriver` → challenge stalls 46s+; fresh-clearance replay blocked). Brave in general: farbling breaks Turnstile (per-site Shields → Block fingerprinting OFF fixes the browser itself).
- Latent bug fixed en route: old code called `self._decode(...)` (module function, not method) — AttributeError swallowed by bare except → always `[]` even without CF.

## Filter/CLI knowledge (4K aliases + ! negation — implemented 2026-09-06)

- All pattern filters (quality/codec/source-type/hdr) match `result.title` client-side; `QUALITY_PATTERNS['2160p']` already matches `2160p|4k|uhd`, `['1080p']` matches `1080p|fhd|full hd`. Only YTS has server-side quality (`QUALITY_MAP` incl. `4k`→`2160p`).
- `-q 4k` was an unknown key → filtered everything out. FIXED: `QUALITY_ALIASES` = {4k→2160p, uhd→2160p, fhd→1080p} in filters.py, resolved inside `_check_pattern` (case-insensitive, applied after stripping `!`).
- `-qx 480p` syntax impossible in argparse (value-taking `-q` swallows `x`). IMPLEMENTED instead: value negation `-q '!480p'` in `FilterEngine._check_pattern` — leading `!` marks an exclude (exclude wins over include; all-exclude list passes unless matched); keys unknown in the primary pattern dict fall back across the engine's other dicts; covers quality/codec/source-type/hdr uniformly. A `-x` argv preprocessor (~10 lines) was considered and rejected as stateful/fragile. `--must-not-contain` remains the raw-regex alternative.

## Pagination (added 2026-09-06)

- `--page N` (default 1) slices the merged → filtered → sorted list: rows `[(N-1)*limit : N*limit]`, with `--limit` as page size. Uniform across all 19 sources; the saved index (`last_results.json`) and `--download` numbering always match the displayed page.
- Deep pages (`--page > 1`) raise the per-source fetch cap via `config.set_max_results_per_source(page × limit)` — scrapers bind the constant at import time, so the helper patches each imported scraper module's global.
- Bound: per-source depth is limited to what the site's first results page serves (knaben ~50 rows → page 11 empty; TorLock pages carry more). Multi-source pools stack, so aggregate pages go deeper.
- Option B — true server-side per-site page params (1337x path page, YTS API `page`, yggtorrent `page`; knaben/torlock/yourbittorrent likely but unverified; TPB apibay and EZTVx RSS can't) — **deferred for later** per user (2026-09-06).
- **rutracker Option B DONE** (2026-09-06, live-verified): see "RuTracker scope narrowing + deep paging" below.

## RuTracker scope narrowing + deep paging (added 2026-09-06, implemented + live-verified)

- Flags: `--rt-cat/-C PRESET` (named presets, server-side `f=` narrowing), `--rt-forum/-F ID` (repeatable raw ids), `--rt-pages/-P N` (1..10 server pages of 50, 5s spacing), `--rt-list-forums/-L` (prints presets + full id→name directory, from `FORUM_DIRECTORY` in rutracker.py). All rutracker-only; harmless warning if `-s rutracker` absent. Empty query + rt flag = browse mode (f=-only, no nm=).
- Server mechanics (verified live): repeated `f=` ANDs forums; deep pages ride `search_id=<token>` from the first response (`start=N*50`, token stable); hard cap 500 rows/query for both search and browse; 16-forum browse URL + browse-mode token pagination both confirmed working (390 results / 100 rows fetched in test).
- `FORUM_PRESETS` originally = {hires: 16 leaves of branch 1299, digitizations: 16 leaves of branch 2219, dsd: union of 32}; ids/names in `FORUM_DIRECTORY`. `CATEGORY_IDS['music']=100` removed (was wrong). Results carry the forum name in the category column (td2), so scoped searches self-identify. Later same day: `hires` renamed `hi-res`, `movies` (30) and `tv-series` (40) added — see addendum below.
- In rt mode the CLI skips the `--page/--limit` slice entirely (`--rt-pages` is the paging; all fetched rows display + save). Cap raise now `max(page*limit, rt_pages*50)`. Timeout `max(args.timeout, rt_pages*8)`.
- Codec filter: `--codec dsd` (also DSD128-style compact forms) = `\b(dsd\d*|sacd|dsf|dff)\b` in `CODEC_PATTERNS` (filters.py).
- CLI hygiene fixes shipped with it: per-source timeout inside `search_single` (replaces the old single global `wait_for` that let one dead source discard every finished source's results — was the main "broad query shows ZERO" cause); failed sources now print `source: search failed — error` to stderr; `--page` starting past the data end warns instead of silently showing an empty table.
- Gotcha fixed during testing: argparse `query` is `None` (not `""`) in browse mode — `_build_url` now guards `if query and query.strip()`, and cli passes `args.query or ""`. Symptom was silent-empty browse searches.

## RuTracker Movies/TV presets, short flags, completion, -h epilog (added 2026-09-06, live-verified)

- Presets now 5: `hi-res` (renamed from `hires`), `digitizations` (16), `dsd` (32), `movies` (30), `tv-series` (40). Exact ids (read from FORUM_PRESETS): movies = [4,7,22,33,93,124,2198,352,511,718,921, 100,101,187,252,271,312,313,572,941,1105,1106,1457,1543,1577,1666,1940,1950,2200,2339]; tv-series = [9,32,81,91,812,920, 189,842,119,242,721,819,1102,1117,1120,1171,1214,1359,1417,1531,1803,2366, 911,704,781,823,1301,1493,1539,1574,1606, 2100,717,915,1242,1938,2102,2103,2104,2412]. Discussion-only and show-specific forums excluded; f=26 (Russian series discussion) dropped, f=1417 (Foreign series DVD) added.
- **`tracker.php?f=` is NOT recursive** (live-verified: f=7 → 50/50 rows from the parent's own forum, zero sub-forum interleaving; f=9 same; f=26 → 0 torrent rows). Parent ids return only the parent's own topics — presets MUST enumerate leaf forums.
- Browse-mode behavior (live-verified): repeated `f=` ORs forums correctly (server count 500 = hard cap on the movies scope), BUT pages arrive forum-major — 50/50 rows from a single forum (movies p1 = f=2339 art-house HD; tv pages = Thai/Indonesia/Singapore forum). Not a bulk-upload artifact (22-23 distinct uploaders, scattered dates). `s`/`o` sort params are IGNORED in browse mode (probe6: seeders column unordered despite s=2&o=2). Music presets under the cap (hi-res: 390) mix normally on page 1. Practical rule: pair the big presets (movies/tv-series) with a search term; browse-only suits the small music presets.
- Short flags: `-C/--rt-cat`, `-F/--rt-forum`, `-P/--rt-pages`, `-L/--rt-list-forums`.
- Bash tab completion: `completions/torrent_search_dl.bash` — source it from .bashrc; completes flags, preset names after -C/--rt-cat, the 19 source names after -s/--sources, formats/sorts/clients; registers both `torrent_search_dl` (alias) and `torrent-search` (pip entry).
- `-h` now ends with a dedicated rutracker section + examples via `_HELP_EPILOG` in cli.py (`epilog=` + `RawDescriptionHelpFormatter`): preset table with forum counts, -F/-P/-L explanations, the 500-cap forum-major tip, and 6 examples (movies 'dune', tv 'severance', 2026+2160p, hi-res browse, DSD+--codec dsd, -F pair).
- Note: `--format json` omits the `category` field (format_json doesn't emit it) — read forum names from `.cache/sessions/last_results.json` (save_results serializes them) instead.
