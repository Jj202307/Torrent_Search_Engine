# Torrent Search Engine — Work Trace Log

## Project Overview
Multi-source torrent search engine with parallel async scrapers and client-side filter engine.
Supports 16 torrent sites (7 JSON/HTML public, 3 HTML with login, several niche/defunct).
Built with httpx + BeautifulSoup4 + rich.

## Architecture

```
torrent_search.sh        # launcher: hides `python3 -m ...`, onboarding, --install-aliases
torrent_search/
├── __init__.py          # Public API exports
├── base.py              # SearchResult, Source, BaseScraper, ScraperResult
├── config.py            # URLs, credentials, rate limits, constants
├── filters.py           # FilterEngine + FilterSpec (regex-based quality detection)
├── normalizer.py        # Size parsing, magnet/hash extraction
├── state.py             # Persists the last search as a numbered result index
├── download.py          # Hands magnets to BiglyBT / any --client
├── cli.py               # CLI entry point (torrent-search command; search + --download/--show)
└── scrapers/
    ├── __init__.py
    ├── tpb.py           # TPB via apibay.org JSON API
    ├── yts.py           # YTS movies via official JSON API
    ├── x1337.py         # 1337x.to HTML scrape
    ├── limetorrents.py  # LimeTorrents.lol HTML scrape
    ├── torlock.py       # TorLock.com HTML scrape (clean table layout)
    ├── torrenting.py    # Torrenting.com HTML scrape
    ├── eztvx.py         # EZTVx.to RSS/HTML scrape (TV shows)
    ├── extto.py         # EXT.to magnet indexer (Cloudflare)
    ├── katcr.py         # Katcr.co (KAT revival) HTML scrape
    ├── torrentparadise.py  # TorrentParadise.org DHT meta-search
    ├── rutracker.py     # RuTracker.org (login, 2.7M torrents)
    ├── yggtorrent.py    # YggTorrent.ws (login, 2.2M torrents)
    ├── zamunda.py       # Zamunda.net (login, Bulgarian)
    ├── maxitorrent.py   # Maxitorrent.net (login, Romanian)
    ├── bitru.py         # BitRu.org (login, Russian)
    └── gimmepeers.py    # GimmePeers.com (login, ex-Demonoid)
```

## Dependency Graph

```
cli.py → filters.py + scrapers/* + base.py + state.py + download.py
download.py → base.py
state.py → base.py + config.py
scrapers/* → base.py + config.py + normalizer.py
filters.py → base.py
config.py → python-dotenv
```

## Site Coverage

| # | Source | Type | Access | Filters | Status |
|---|---|---|---|---|---|
| 1 | TPB (apibay) | JSON API | Free | Category | ✓ Live |
| 2 | YTS | JSON API | Free | Quality, Genre, Rating | ✓ Live |
| 3 | 1337x | HTML | Free | Category, Sort | ✓ |
| 4 | LimeTorrents | HTML | Free | Category, Sort | ✓ |
| 5 | TorLock | HTML | Free | Category | ✓ |
| 6 | EZTVx | RSS/HTML | Free | None (TV only) | ✓ |
| 7 | EXT.to | HTML | Free (Cloudflare) | Minimal | ✓ |
| 8 | RuTracker | HTML (login) | Free reg | Category, Sort | ✓ |
| 9 | YggTorrent | HTML (login) | Free reg | Category, Sort | ✓ |
| 10 | Zamunda | HTML (login) | Free reg | Category | ✓ |
| 11 | Maxitorrent | HTML (login) | Free reg | Category | ✓ |
| 12 | BitRu | HTML (login) | Free reg | Category | ✓ |
| 13 | GimmePeers | HTML (login) | Free reg | Category | ✓ |
| 14 | Katcr | HTML | Free | Category | ✓ |
| 15 | TorrentParadise | HTML | Free | Minimal | ✓ |
| 16 | Torrenting | HTML | Free | Category | ✓ |

Dead/low-uptime sites (scrapers not written):
- TorrentGalaxy.to — connection failure
- GloTorrents (glodls.to) — 521 error
- TorrentFunk, Torrents.io, 7torrents, TorrentDownloads, Demonoid — defunct

## Filter Engine Capabilities

All filtering is client-side (regex on normalized titles) since almost no public torrent site supports server-side HD/4K/HQ filtering.

### Quality Detection
- 2160p (4K, UHD), 1080p (FHD, Full HD), 720p, 480p
- Pattern matching on resolution keywords in title

### Codec Detection
- Audio: FLAC, ALAC, MP3, AAC, DTS, TRUEHD (Atmos), OPUS
- Video: H264 (AVC/x264), H265 (HEVC/x265), AV1, XVID
- Audio channels: 5.1, 7.1, ATMOS

### Source Type Detection
- REMUX, WEB-DL, WEBRIP, BLURAY, BDRIP, HDRIP, DVDRIP, CAM, SCREENER

### HDR Detection
- HDR, HDR10+, Dolby Vision

### Size & Seeders
- Min/max size in GB, minimum seeders

## Installation

```bash
# Install core dependencies
pip install httpx beautifulsoup4 lxml rich python-dotenv tenacity tqdm

# Optional: Cloudflare bypass
pip install curl-cffi

# Optional: Headless browser for EXT.to
pip install playwright && playwright install chromium

# For login-requiring sites, create .env file:
# RUTRACKER_USERNAME=your_user
# RUTRACKER_PASSWORD=your_pass
# YGGTORRENT_USERNAME=your_user
# YGGTORRENT_PASSWORD=your_pass
# ... etc
```

## Usage

```bash
# Search all sources (results are saved as a numbered index)
torrent-search "ubuntu 22.04"

# Filter by quality and seeders
torrent-search "debian" --quality 1080p --min-seeders 10

# Search specific sources only
torrent-search "avatar" --sources yts,tpb

# JSON output for automation
torrent-search "movie" --format json

# Audio quality filter (FLAC music)
torrent-search "dark side of the moon" --codec FLAC --source-type REMUX --min-size 0.5

# 4K movie with HDR
torrent-search "dune" --quality 2160p --hdr HDR --min-size 10 --source-type BLURAY

# List all available sources
torrent-search --list-sources

# Download numbered results from the last search into BiglyBT
torrent-search --download 1,3,4        # specific results
torrent-search --download 1-3,7        # ranges work too
torrent-search --download all          # everything

# Re-print the saved index
torrent-search --show

# Convenience launcher (no python3 -m, onboarding, alias installer)
./torrent_search.sh "ubuntu 22.04"
./torrent_search.sh --download 2,5
./torrent_search.sh --install-aliases   # adds torrent_search_dl aliases to ~/.bashrc
```

## Key Design Decisions

1. **Async throughout** — httpx.AsyncClient for all HTTP; asyncio.gather for parallel site search
2. **Graceful degradation** — if a scraper fails, other sources continue; failed source returns empty
3. **Client-side filtering** — only TPB (category) and YTS (quality/genre/rating) support server-side filters; all HD/4K/HQ/FLAC filtering happens on normalized titles via regex
4. **No external accounts required** — all login-required sites are FREE registration (no invites), credentials via .env
5. **Single common schema** — SearchResult dataclass unifies all sources for consistent filtering/sorting
6. **Persisted result index** — every search saves its displayed results to `.cache/sessions/last_results.json`, so a followup `--download 1,3,4` works without re-querying
7. **Client handoff** — `download.py` resolves the client (`flatpak run com.biglybt.BiglyBT` → `biglybt` binary → any `--client` on PATH) and opens each result's magnet (fallback: torrent URL, then hash-built magnet)

## Known Limitations

- EXT.to blocked by Cloudflare; needs curl_cffi or playwright
- RuTracker uses windows-1251 encoding; title text may have Cyrillic
- YggTorrent domain rotates periodically; update config.SITE_URLS
- GimmePeers is now serving as revott.me; structure may change
- Magnet links not available on all search result pages (need to scrape detail pages)
- Some login-required sites may need session cookies refreshed periodically

## Verification

- Core imports: `~/check_core.sh` — tests base.py, filters.py, normalizer.py
- Scraper imports: `~/check_scrapers.sh` — tests each scraper module can be imported
- End-to-end: `torrent-search "ubuntu" --sources tpb,yts --format json` — live API test
