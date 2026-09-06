# Handover — Torrent Search Engine

Durable, current-state operational reference for the Torrent Search Engine repo. Date history of the two build sessions lives in changelog.md; day-by-day working notes live in work_trace_log.md.

## What this project is

A multi-source torrent search engine (CLI + Python package) with 19 parallel async scrapers, a client-side filter engine for HD/4K/HQ/FLAC etc., and a common result schema. Built at user request to query free, no-subscription, no-invite BitTorrent sites, sorted by size/seeders, filtered by quality.

## Source catalog (current state)

Counts are self-reported estimates — no authoritative central database exists. The one verified figure: **RuTracker = 2.7M torrents** (Wikipedia, May 2026).

| ~Count | Site | Access |
|---|---|---|
| ~8M | The Pirate Bay | free, no account |
| 2.7M | RuTracker.org | free, optional signup |
| ~2.2M | YggTorrent | free, mandatory open signup |
| ~1.5M | 1337x | free, optional signup |
| ~1.2M | LimeTorrents | free |
| ~1.2M | Zamunda.net | free signup |
| ~1M | Maxitorrent.net | free signup |
| ~0.5M | EXT.to | free, magnet indexer |
| ~0.4M | EZTVx.to | free, TV only |
| ~0.3M | Torrenting.com | free |
| ~0.2M | TorLock | free |
| ~0.15M | YTS.bz | free, movies only |
| ~0.15M | GimmePeers (ex-Demonoid) | free signup |
| ~0.12M | BitRu | free signup |
| ~0.1M | Katcr.co | free |
| — | TorrentParadise | DHT meta-search |
| — | yourbittorrent.com | free |
| — | knaben.org | free, multi-tracker meta-search |
| — | audiobookbay.lu | free, audiobooks (WordPress) |

Removed/excluded/dead: removed by user during build — Nyaa.si, Pornolab.net, AnimeTosho, Skidrowreloaded, FitGirl Repacks, idope.se, BTDB; dropped as non-integratable — snowfl.com (SPA with rotating-key JSON API; key vars no longer extractable from b.min.js); excluded by criteria (paid/invite-only) — IPTorrents, AnimeBytes, TorrentLeech; dead/defunct — TorrentGalaxy.to (memecoin promo), GloTorrents (glodls.to), TorrentFunk, 7torrents, Torrents.io, Demonoid (low activity), TorrentDownloads, yts.mx, zooqle.to, btdb.to, torrent.by, ilcorsaronero.info (hijacked), rarbg family (2023).

## Verified live domains (current state)

Live (all 19 integrated):
- thepiratebay.org — reachable; API at apibay.org works
- yts.bz — live (yts.gg is the current official gateway; yts.mx stopped Jan 2026); **API base is `https://movies-api.accel.li/api/v2`** (yts.bz/api/v2 now 301-redirects)
- limetorrents.lol — live
- torlock.com — live, clean 7-column table
- ext.to — live, Cloudflare-walled
- eztvx.to — live (403 on robots)
- zamunda.net — live (403 on robots)
- maxitorrent.net — live
- gimmepeers.com — serves revott.me login page
- katcr.co — robots disallow all
- yggtorrent.ws — live, domain rotates periodically
- rutracker.org — live but Cloudflare-walled (managed challenge; see RuTracker section)
- yourbittorrent.com — live (note: yourbitorrent.com, one "r", is a dead different domain)
- knaben.org — live
- audiobookbay.lu — live but TCP-unreachable from this network (geo); verified via relay

Robots-walled but alive (policy call, not integrated): torrent9.so, oxtorrent.co, cpasbien.run, btscene.cc, torrentproject2.net, animetosho.org (`/search`).

Cloudflare-walled: rutracker.org (managed challenge), ext.to, bitsearch.to, kickasstorrents.to, bt4g.

Dead: yts.mx (stopped Jan 2026), torrentgalaxy.to (memecoin promo), glodls.to, zooqle.to, btdb.to, 7torrents, torrents.io, torrent.by, ilcorsaronero.info (hijacked), rarbg family (2023).

Verified live, not integrated: rutor.info (`/search/{q}/0/0/0`, inline magnet+.torrent — best candidate), torrentfunk.com (+ torrentfunk2.com mirror, `/all/torrents/{q}.html`), torrentdownloads.pro (`/search/?search={q}`).

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
- RuTracker: POST `/forum/login.php`, cookie `bb_data`; search `/forum/tracker.php?nm={query}`; windows-1251 encoding. Lib: `rutracker-api`. (Note: the form-login path is unusable while Cloudflare guards login.php — current auth is the Firefox cookie bridge, see the RuTracker section.)
- YggTorrent: POST login, search `/engine/search?name={query}&category={id}` (2140 films, 2141 series, 2142 musique, 2143 jeux-video, 2144 applications, 2145 ebooks, 2146 animation); French units Go/Mo. Lib: `yggtorrentapi`.
- Zamunda, Maxitorrent, BitRu, GimmePeers: forum-style login + search, session cookie persistence.

### Additional integrated sources
- **yourbittorrent.com**: route `/?q={query}`; result rows — title `a.yb-tname` with a `^/torrent/\d+/` relative href; size/added `td[data-label=…]`; seeders `td.sd`, peers `td.pr`; category `a.yb-cat[title]`. `.torrent` at `/down/{id}.torrent` (200, bencode). Rows also carry injected t0r.space spam (same as TorLock) — filtered by the relative-href requirement. The IP can get 403-flagged after burst probing; the block is server-side and may clear.
- **knaben.org**: route `/search/{query}` **path** (the `?query=` form is a status-dashboard stub). Rows: `tr` with `a[href^='magnet:']`; td[0] category, td[1] title+magnet, td[2] size, td[3] date, td[4] seeders, td[5] leechers, td[6] source site. Multi-tracker cached meta-search (aggregates TPB/YTS/etc). The magnet IS the row href; info_hash from btih.
- **audiobookbay.lu**: route `/?s={query}` (WordPress). Rows: `div.post`; title `postTitle h2 a` → `/abss/{slug}/`; File Size regex over the post div; magnet/hash on the detail page. Detail pages publish `Info Hash:` + a `/downld0?downfs=` link, no magnet anchor — the scraper rebuilds the magnet from the hash. ~9 results/page, semaphore(4) detail fetches.

Registration touch points for any new source: `base.py` Source enum, `config.py` SITE_URLS + RATE_LIMITS, `scrapers/<name>.py`, `scrapers/__init__.py`, `cli.py` `_scraper_modules`.

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
- Client handoff: `download.py` opens each result's magnet in BiglyBT — launched via `flatpak run --command=/app/biglybt/biglybt com.biglybt.BiglyBT` (the stock flathub runner drops all CLI args), fallback `biglybt` binary, or any `--client` on PATH; missing magnets fall back to `torrent_url`, then a hash-built magnet.

## Download pipeline

- `download.py` converts `.torrent` URLs to magnets client-side before handoff: fetch → bencode `_scan_torrent` (info-dict span + announce/announce-list trackers) → sha1 → `xt=urn:btih:` magnet with `dn`/`tr`. Hash verified against TPB's published magnet (e498d30e…). Needed because the BiglyBT flatpak sandbox can't fetch some mirrors and can't read `/tmp`.
- `ensure_magnet` (the fetching side): sends `DEFAULT_USER_AGENT`, 3 attempts with backoff, bencode validation; failed conversions fall back to the raw URL and the summary marks them `(direct URL — magnet conversion failed)`.
- `rutracker.org` `.torrent` URLs route to rutracker's module-level `fetch_torrent_magnet()` — plain httpx can't reach `dl.php`.
- BiglyBT client readiness is probed at `_READY_PROBES` (127.0.0.1:6880): first URI launches the client, the listener is polled up to 60s, then all URIs are resent (client dedupes), 0.25s stagger.
- Alt clients: `--client qbittorrent` works via PATH fallback; qBittorrent is the recommendation if BiglyBT is dropped (magnet argv works cold+warm via single-instance IPC). ktorrent/rtorrent have handoff caveats.
- BiglyBT flatpak data: `~/.var/app/com.biglybt.BiglyBT/.biglybt/` (downloads.config, torrents/, logs/); stop with `flatpak kill com.biglybt.BiglyBT`.

## Key file map

```
torrent_search.sh        # launcher: hides `python3 -m ...`, onboarding (only when $# -eq 0), --install-aliases
torrent_search/
├── base.py        # SearchResult, Source, BaseScraper (has supports_browse flag; rutracker stays False), ScraperResult
├── config.py      # SITE_URLS, CREDENTIALS, RATE_LIMITS, MAX_RESULTS_PER_SOURCE, set_max_results_per_source()
├── filters.py     # FilterEngine (QUALITY/CODEC/SOURCE/HDR/CHANNEL/ENCODING patterns + QUALITY_ALIASES), FilterSpec
├── normalizer.py  # parse_size, parse_seeders_leechers, extract_magnet, extract_info_hash, to_int
├── state.py       # save_results/load_results: persisted numbered index (.cache/sessions/last_results.json)
├── download.py    # resolve_client/result_uri/download_results/print_download_summary → BiglyBT handoff, ensure_magnet
├── cli.py         # async CLI: search flags + --rt-cat/-C --rt-forum/-F --rt-pages/-P --rt-list-forums/-L, --yts-sort,
│                  # --page/--limit, --show/--download/--client/--no-hints; _HELP_EPILOG rutracker docs in -h
└── scrapers/      # 19 scrapers, each with async search()/alive()/close(), Source set; rutracker.py holds
                   # FIREFOX_UA, FORUM_PRESETS, FORUM_DIRECTORY (the id→name source of truth)
completions/torrent_search_dl.bash   # bash tab completion: flags, preset names after -C/--rt-cat, the 19 source
                                     # names after -s/--sources, formats/sorts/clients; registers both
                                     # torrent_search_dl (alias) and torrent-search (pip entry)
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

## RuTracker — operational reference

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
- **Critical: request volume burns the clearance.** A 50-fetch burst (magnet conversion for all results at search time) made CF re-challenge the replay client; invisible auto-rotated clearances do NOT replay. A **checkbox-solved** clearance (user clicks verification manually in Firefox) replays fine. Search is exactly 1 request (`tracker.php`); magnets are fetched only per downloaded torrent.
- Forum index is NOT CF-guarded; only login.php/tracker.php/dl.php are.
- Parser: 10-td rows — td2 category, td3 title (`a.tLink`), td4 uploader, td5 `td.tor-size` (`data-ts_text` = exact bytes; contains `a.tr-dl` → `dl.php?t=<id>` .torrent link), td6 seeders, td7 leechers, td9 added. windows-1251. `fetch_torrent_magnet()` (module-level) fetches dl.php through a fresh cookie session; `download.ensure_magnet` routes `rutracker.org` URLs to it (plain httpx can't reach dl.php).
- Dead ends proven: httpx/curl_cffi direct (403), playwright+patchright chromium any mode, patchright firefox headless+headed (challenge starts, never completes), turnstile-iframe click (widget iframe never renders under automation), real Firefox binary headless via Marionette (`navigator.webdriver` → challenge stalls 46s+; fresh-clearance replay blocked). Brave in general: farbling breaks Turnstile (per-site Shields → Block fingerprinting OFF fixes the browser itself).
- Latent bug fixed en route: old code called `self._decode(...)` (module function, not method) — AttributeError swallowed by bare except → always `[]` even without CF.

## RuTracker — server facts, scope flags, presets

### Flags and browse mode
- Flags: `--rt-cat/-C PRESET` (named presets, server-side `f=` narrowing), `--rt-forum/-F ID` (repeatable raw ids), `--rt-pages/-P N` (1..10 server pages of 50, 5s spacing), `--rt-list-forums/-L` (prints presets + full id→name directory, from `FORUM_DIRECTORY` in rutracker.py). All rutracker-only; harmless warning if `-s rutracker` absent. Empty query + rt flag = browse mode (f=-only, no nm=).
- Browse-mode note: argparse `query` is `None` (not `""`) in browse mode — the CLI passes `args.query or ""`, and `_build_url` guards `if query and query.strip()`. (Symptom of the old bug was silent-empty browse searches.)
- Short flags: `-C/--rt-cat`, `-F/--rt-forum`, `-P/--rt-pages`, `-L/--rt-list-forums`.

### Server mechanics (verified live)
- `tracker.php?f=` is NOT recursive: f=7 → 50/50 rows from the parent's own forum, zero sub-forum interleaving; f=9 same; f=26 → 0 torrent rows. Parent ids return only the parent's own topics — presets MUST enumerate leaf forums.
- Repeated `f=` ANDs forums; deep pages ride `search_id=<token>` from the first response (`start=N*50`, token stable); hard cap 500 rows/query for both search and browse.
- Browse-mode paging arrives **forum-major**: 50/50 rows from a single forum per page (movies p1 = f=2339 art-house HD; tv pages = Thai/Indonesia/Singapore forum). Not a bulk-upload artifact (22-23 distinct uploaders, scattered dates). `s`/`o` sort params are IGNORED in browse mode (probe6: seeders column unordered despite s=2&o=2). Music presets under the cap (hi-res: 390) mix normally on page 1.
- **`nm=` does not index the `[year, ...]` metadata bracket** → year-only queries like `'2026'` return 0 by construction. Year examples must be browse+client-filter instead (e.g. `-F 1457 -P 2 -q 2160p`, 100 rows).

### Query × multi-f= loss rule
- `nm=` combined with MANY `f=` silently loses matches server-side. nm=dune: single f=1457 → 8 correct rows; site-wide → 50; 30-forum movies preset → 6 rows (only the 1984 Lynch film, wrong); first-15 forums → 0. 32-forum 'DSD' -C dsd degraded but usable (16 rows). 2-forum 'flac' f=1755+1756 → 50 (fine). Rule: **query + 1-2 `-F` ids, or browse-only presets.** Server behavior is inconsistent even then — treat preset+query as "do not use".

### Presets and forum ids
- Presets: 5 total — `hi-res` (16), `digitizations` (16), `dsd` (32, union of hi-res + digitizations), `movies` (106), `tv-series` (78). `CATEGORY_IDS['music']=100` was removed (was wrong). Results carry the forum name in the category column (td2), so scoped searches self-identify. Discussion-only forums excluded (`f=26` etc.).
- US & Canada TV forums are present: real leaf ids f=235 (standard), f=266 (HD), f=1669 (UHD). `tv-series` covers US shows ('severance' in f=266/1669 → 6 rows each).
- **rutracker RECYCLES dead forum ids** — old ids silently point at different forums now: 32 (was "Old Russian series" label → actually Обсуждение), 91 (→ single show "Я знаю твои секреты"), 1417 (→ Breaking Bad, not "Foreign series DVD"), 1214 (→ Australia & NZ), 1359 (→ Web series), 704 (→ Turkey), 781 (→ multi-country co-pro), 1301 (→ India), 1539 (→ LatAm subtitled), 1574 (→ LatAm dubbed), 915 (→ Korean), 1242 (→ Korean HD), 2102 (→ Asian clips), 2412 (→ Thailand/Indonesia/Singapore). Dropped as dead/repurposed-elsewhere: 32, 1117, 823, 1606, 1938, 2103, 2104, 1493 (1493 is now "Спектакли без перевода" under Theater → moved to movies preset). **Re-verify ids against the live tree before trusting any id.**
- **Plain `index.php` TRUNCATES subforum lists** (f=189 showed 1 of 26) — `index.php?c=N` category pages are the complete source; f=235/266/1669 appear nowhere on plain index.php. Viewforum pages list child forums; recurse into non-leaves. Archives (190/665/931) are hidden on category pages but exist on viewforum.
- Preset exclusions: discussion/Ищу/Архив/некондиционные/Предложения/Для общения/Поговорим(chat) forums. Directory labels: translated live Russian names (pattern map in /tmp/opencode/gen_presets.py); untranslatable show forums keep Russian/live names. Branch roots that host topics AND subforums ("both" forums: 189, 4, 921, …) stay in the presets so parent-hosted topics aren't missed.
- Regeneration flow for future edits: regenerate via /tmp/opencode/gen_presets.py against a fresh tree_walk.json, splice between `FORUM_PRESETS["movies"]` and `FORUM_NAMES`.

### Silent-exit paths and the "re-run once" caveat
- **Silent-exit paths in `rutracker.search()`** (lines ~481-522): `_login()` False → [], HTTP 403/429/503 → [], bare except → swallowed. CLI prints no failure line, so empty tables look like success. Transient cookie/clearance rotation produced a full all-zero batch once; a raw curl_cffi probe (rt_probe7 pattern: status + row count + cf-marker scan) distinguishes "site healthy" from "scraper path broken".
- rutracker occasionally returns 0 for a shape that works minutes later (whole batch once came back empty incl. proven queries; `pink floyd -F 1755` → 0 once, site-wide 50 right after). If a known-good example returns 0, re-run once before concluding.

### Verified recipes
- `dune -F 1457 -q 2160p` → 8
- `severance -F 266` → 6
- `severance -F 1669` → 6
- browse `-F 1457 -P 2 -q 2160p` → 100
- site-wide `severance` → 50
- `'DSD' -C dsd --codec dsd` → 16
- `'flac' -F 1755 -F 1756` → 50
- `'pink floyd' -F 1756` → 50 (HowToUse's old `pink floyd -C hi-res` → 0 twice — preset+query unreliable even at 16 forums, while the 32-f DSD preset returned 16)

## Filter/CLI reference

- All pattern filters (quality/codec/source-type/hdr) match `result.title` client-side; `QUALITY_PATTERNS['2160p']` already matches `2160p|4k|uhd`, `['1080p']` matches `1080p|fhd|full hd`. Only YTS has server-side quality (`QUALITY_MAP` incl. `4k`→`2160p`).
- `QUALITY_ALIASES` = {4k→2160p, uhd→2160p, fhd→1080p} in filters.py, resolved inside `_check_pattern` (case-insensitive, applied after stripping `!`).
- `-q 4k` used to be an unknown key → filtered everything out; aliases fix that.
- Value negation: `-q '!480p'` in `FilterEngine._check_pattern` — leading `!` marks an exclude (exclude wins over include; all-exclude list passes unless matched); keys unknown in the primary pattern dict fall back across the engine's other dicts; covers quality/codec/source-type/hdr uniformly. `--must-not-contain` remains the raw-regex alternative. (A `-x` argv preprocessor was considered and rejected as stateful/fragile.)
- Codec filter: `--codec dsd` (also DSD128-style compact forms) = `\b(dsd\d*|sacd|dsf|dff)\b` in `CODEC_PATTERNS` (filters.py).
- Output note: `--format json` omits the `category` field (format_json doesn't emit it) — read forum names from `.cache/sessions/last_results.json` (save_results serializes them) instead.

## Pagination

- `--page N` (default 1) slices the merged → filtered → sorted list: rows `[(N-1)*limit : N*limit]`, with `--limit` as page size. Uniform across all 19 sources; the saved index (`last_results.json`) and `--download` numbering always match the displayed page.
- Deep pages (`--page > 1`) raise the per-source fetch cap via `config.set_max_results_per_source(page × limit)` — scrapers bind the constant at import time, so the helper patches each imported scraper module's global.
- Bound: per-source depth is limited to what the site's first results page serves (knaben ~50 rows → page 11 empty; TorLock pages carry more). Multi-source pools stack, so aggregate pages go deeper.
- In rutracker mode the CLI skips the `--page/--limit` slice entirely (`--rt-pages` is the paging; all fetched rows display + save). Cap raise is `max(page*limit, rt_pages*50)`. Timeout is `max(args.timeout, rt_pages*8)`. Rutracker deep paging is true server-side (search_id token); server-side per-site page params for the other sources (1337x path page, YTS API `page`, yggtorrent `page`; knaben/torlock/yourbittorrent likely but unverified; TPB apibay and EZTVx RSS can't) are deferred.

## Browse + API quirks (other sources)

- `BaseScraper.supports_browse` flag (False default; yts+eztvx True; rutracker stays False — the CLI checks its -C/-F separately). CLI gate: empty query allowed only if every selected source supports browse (or rutracker -C/-F given); otherwise prints help. Launcher torrent_search.sh onboarding runs only when `$# -eq 0` (old case `"${1:-}"` swallowed an empty first arg).
- YTS API (movies-api.accel.li) quirks: limit>50 clamps to 20 movies; only limit=50 is a full page → yts.py paginates internally (PAGE_SIZE 50, MAX_PAGES 20, 0.35s delay, window=rows, dedupe (movie_id, torrent_hash), past-the-end = HTTP 200 with `movies` key ABSENT, movie_count reliable; `page` kwarg shifts the loop for standalone callers). sort_by: download_count/rating/year/title honored; seeds silently ignored (date fallback). Mirror strips movie-level seeds/download_count.
- eztvx browse: RSS is a hard 30-item buffer, ALL params ignored (limit/page/quality/category); /releases/ HTML is Cloudflare-403 (fallback effectively dead); beta API GET /api/get-torrents (limit 1-100, page 1-100) works from this host, pages cleanly, seeds populated, imdb_id+hash+magnet_url per row → the primary browse source (RSS/HTML kept as fallbacks). imdb_id enables a future --group-series (series-level popularity, TV's download_count equivalent).
- CLI recap: sources parsed above the empty-query gate; `--yts-sort` flag (warns if yts not selected); saved-session label "<sources> browse"; epilog + HowToUse examples.
- Verdict: NO server-side TV-popularity sort in any indexed source (eztvx all surfaces + yts movies-only; knaben API orderBy unreachable, limetorrents /top100-TV-shows-torrents/ mirror connection-dead, katcr JS-walled — future candidates only).
- Working recipes: `'' -s yts` | `'' -s yts --yts-sort download_count` | `'' -s eztvx` | `'' -s eztvx --sort seeders --min-seeders 5` | `'' -s yts,eztvx --limit 100`.
- CLI hygiene: per-source timeout inside `search_single` (replaces a single global `wait_for` that let one dead source discard every finished source's results — was the main "broad query shows ZERO" cause); failed sources print `source: search failed — error` to stderr; `--page` starting past the data end warns instead of silently showing an empty table.
