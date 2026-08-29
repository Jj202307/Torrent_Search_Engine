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
