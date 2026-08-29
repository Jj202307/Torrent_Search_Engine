# HowToUse — Torrent Search Engine

A multi-source torrent search CLI. Queries 16 free BitTorrent index sites in parallel, normalizes results, filters client-side (HD/4K/HQ/FLAC etc.), outputs table/JSON/simple, and can hand numbered results off to BiglyBT for download.

## 1. Installation

Requires Python 3.10+.

```bash
cd ~/Downloads/Projects/Torrent_Search_Engine

# Core dependencies
pip install httpx beautifulsoup4 lxml rich python-dotenv tenacity tqdm

# Optional: Cloudflare TLS bypass (EXT.to)
pip install curl-cffi

# Optional: headless browser for heavily-protected sites
pip install playwright && playwright install chromium
```

To install as a command (`torrent-search`):

```bash
pip install -e .
```

(If pip complains about permissions, install with `pip install --user` or the system package manager equivalent — anything requiring sudo, run manually.)

### Login credentials (free-registration sites only)

Create `.env` in the project root (or export env vars). Only needed if you search the login-required sites:

```bash
RUTRACKER_USERNAME=your_user
RUTRACKER_PASSWORD=your_pass
YGGTORRENT_USERNAME=your_user
YGGTORRENT_PASSWORD=your_pass
ZAMUNDA_USERNAME=your_user
ZAMUNDA_PASSWORD=your_pass
MAXITORRENT_USERNAME=your_user
MAXITORRENT_PASSWORD=your_pass
BITRU_USERNAME=your_user
BITRU_PASSWORD=your_pass
GIMMEPEERS_USERNAME=your_user
GIMMEPEERS_PASSWORD=your_pass
```

## 2. Quick start

```bash
# List available sources
python3 -m torrent_search.cli --list-sources
# or if installed: torrent-search --list-sources

# Search everything
python3 -m torrent_search.cli "ubuntu server"

# Simple text output
python3 -m torrent_search.cli "avatar" --format simple

# Download results #1, #3, #4 of the last search into BiglyBT
python3 -m torrent_search.cli --download 1,3,4

# Easier: use the bundled launcher instead of `python3 -m ...`
./torrent_search.sh "ubuntu server"
./torrent_search.sh --download 1,3,4
```

## 3. All options

```
torrent-search QUERY [OPTIONS]

  --sources, -s        Comma-separated sources: tpb,yts,1337x,... (default: all)
  --min-seeders N      Minimum seeder count
  --quality, -q        Quality: 2160p, 1080p, 720p, 480p (repeatable)
  --codec              Audio codec: FLAC, ALAC, MP3, AAC, DTS, TRUEHD, OPUS (repeatable)
  --source-type        Release: REMUX, WEB-DL, BLURAY, WEBRIP, DVDRIP, CAM, ... (repeatable)
  --hdr                HDR: HDR, DOLBY_VISION, HDR10+ (repeatable)
  --min-size GB        Minimum size in GB (float)
  --max-size GB        Maximum size in GB (float)
  --must-contain T     Keyword/pattern that must be in title (repeatable)
  --must-not-contain T Keyword/pattern that must NOT be in title (repeatable)
  --limit N            Max results shown (default: 50)
  --sort FIELD         seeders | size (default: seeders)
  --format FMT         table | json | simple (default: table)
  --timeout SECONDS    Total search timeout (default: 30)
  --no-progress        Disable progress bar
  --list-sources       List available sources and exit
  --download SPEC      Download results by index: 1,3-5 or all. Without a query,
                       uses the last saved results.
  --show               Re-print the last saved results (numbered).
  --client NAME        BitTorrent client to hand magnets to (default: biglybt).
  --no-hints           Do not print usage examples under results.
```

## 4. Examples

```bash
# 4K movies with HDR, at least 10GB, minimum 10 seeders
python3 -m torrent_search.cli "dune" --quality 2160p --hdr HDR --source-type BLURAY --min-size 10 --min-seeders 10

# FLAC music from a couple of sources only
python3 -m torrent_search.cli "dark side of the moon" --sources tpb,1337x --codec FLAC --min-seeders 5

# JSON output for scripting/automation
python3 -m torrent_search.cli "debian" --format json --limit 10

# Filter out CAM/TS quality and small files
python3 -m torrent_search.cli "avatar" --must-not-contain cam,ts --min-size 3 --quality 1080p

# Multi-word phrase and larger results
python3 -m torrent_search.cli "ubuntu 22.04" --min-seeders 5 --limit 20 --format simple
```

## 5. Downloading results (BiglyBT)

Every search stores its displayed results as a numbered index, so you download after you search — no re-query needed.

```bash
# 1. Search once. Results are numbered 1..N and saved automatically.
torrent_search_dl "dune" --quality 2160p --min-seeders 10

# 2. Download the ones you want into BiglyBT.
torrent_search_dl --download 1,3,4        # picks results #1, #3, #4
torrent_search_dl --download 1-3,7        # ranges work too
torrent_search_dl --download all          # everything

# 3. Re-print the saved index later, before picking numbers.
torrent_search_dl --show
```

- Without a query, `--download` reads the last saved index. With a query it searches first, then downloads the selected numbers.
- Each result uses its magnet link (or `.torrent` URL / hash-derived magnet as fallback) and is handed to BiglyBT, which adds it to the running instance or starts it.
- Client detection: `flatpak run com.biglybt.BiglyBT` first, then a `biglybt` binary on PATH. Override with `--client NAME`.

### Aliases

The bundled launcher removes the need to type `python3 -m torrent_search.cli`:

```bash
cd ~/Downloads/Projects/Torrent_Search_Engine
./torrent_search.sh --install-aliases     # adds the two aliases to ~/.bashrc
source ~/.bashrc

torrent_search_dl "debian"                 # search
torrent_search_dl --download 2,5           # download from the saved index
torrent_search_dl_howto                    # same as --help, all flags
torrent_search_dl                          # no args: onboarding / where to start
```

## 6. Available sources

| Key | Site | Type | Login needed |
|---|---|---|---|
| `tpb` | The Pirate Bay (apibay API) | JSON API | no |
| `yts` | YTS movies (API) | JSON API | no |
| `1337x` | 1337x | HTML | no |
| `limetorrents` | LimeTorrents | HTML | no |
| `torlock` | TorLock | HTML | no |
| `torrenting` | Torrenting.com | HTML | no |
| `eztvx` | EZTVx (RSS) | RSS/HTML | no |
| `extto` | EXT.to (Cloudflare) | HTML | no |
| `katcr` | KAT revival | HTML | no |
| `torrentparadise` | TorrentParadise | HTML | no |
| `rutracker` | RuTracker | HTML | yes (free) |
| `yggtorrent` | YggTorrent | HTML | yes (free) |
| `zamunda` | Zamunda | HTML | yes (free) |
| `maxitorrent` | Maxitorrent | HTML | yes (free) |
| `bitru` | BitRu | HTML | yes (free) |
| `gimmepeers` | GimmePeers/revott | HTML | yes (free) |

Notes:
- `rutracker` text is windows-1251/Cyrillic.
- `yggtorrent` domain rotates; if it stops working, update `SITE_URLS['yggtorrent']` in `torrent_search/config.py`.
- `extto` may need `pip install curl-cffi` (Cloudflare).
- TorrentGalaxy, GloDLS, TorrentFunk, Torrents.io, 7torrents, TorrentDownloads, Demonoid were researched but excluded (defunct/low uptime or dropped by request).

## 7. Python API (programmatic use)

```python
import asyncio
from torrent_search.scrapers.tpb import TPBScraper
from torrent_search.scrapers.yts import YTSScraper
from torrent_search.filters import FilterEngine, FilterSpec

async def main():
    tpb = TPBScraper()
    yts = YTSScraper()

    results = []
    tpb_res = await tpb.search("ubuntu server", category="0")
    yts_res = await yts.search("avatar", quality="1080p", minimum_rating=7)

    results.extend(tpb_res)
    results.extend(yts_res)

    await tpb.close()
    await yts.close()

    # Filter client-side
    engine = FilterEngine()
    spec = FilterSpec(min_seeders=10, qualities=["1080p"], min_size_gb=2.0)
    results = engine.apply(results, spec)
    results = engine.sort_by_seeders(results)

    for r in results:
        print(f"[{r.source.value}] S:{r.seeders} {r.size_bytes/1024**3:.2f}GB  {r.title}")

asyncio.run(main())
```

Search kwargs passed through per source:
- `tpb`: `category` (numeric cat code)
- `yts`: `quality`, `genre`, `minimum_rating`, `sort_by`, `page`, `limit`
- `1337x`: `category` (movies/tv/music/games/apps/anime/documents/other), `sort_field`, `sort_order`, `page`
- `limetorrents`, `torlock`, `katcr`, `torrenting`: `category`
- `rutracker`, `yggtorrent`, `zamunda`, `maxitorrent`, `bitru`, `gimmepeers`: `category`
- `extto`: `sort`

## 8. Filter engine details

All filtering is client-side regex on normalized titles (only TPB category + YTS quality/genre/rating are server-side).

- **Quality**: `2160p|4k|uhd`, `1080p|fhd|full hd`, `720p`, `480p`
- **Audio codecs**: `FLAC`, `ALAC`, `MP3|320 kbps`, `AAC`, `DTS`, `TRUEHD|atmos`, `OPUS`
- **Release types**: `REMUX`, `WEB-DL`, `WEBRIP`, `BLURAY`, `BDRIP|BRRIP`, `HDRIP`, `DVDRIP`, `CAM|TS|TC`, `SCREENER`
- **HDR**: `HDR|HDR10`, `DOLBY VISION|DV`, `HDR10+`
- **Size**: min/max in GB on `size_bytes`
- **Seeders**: minimum count

## 9. Troubleshooting

- **No results from a source** → the site may be down/blocked. Run `--list-sources`; re-check the domain manually.
- **`extto` fails** → `pip install curl-cffi`, or expect Cloudflare blocks from datacenter IPs.
- **Login sites return nothing** → create `.env` with credentials; verify the account is active.
- **Timeout** → raise `--timeout` or narrow `--sources`.
- **Wide table clipped in narrow terminal** → use `--format simple`.
- **YTS 301/empty** → config already points to `movies-api.accel.li/api/v2`; if that changes again, update `SITE_URLS['yts_api']`.
- **Import errors** → ensure all requirements installed (`pip install -r requirements.txt`).
- **`--download` says the client isn't found** → install BiglyBT (`flatpak install com.biglybt.BiglyBT`) or pass `--client <binary-on-path>`.
- **`--download` without a prior search** → run a search first; the numbered index is only saved when a search completes.

## 10. Project layout

```
torrent_search.sh    # launcher: hides `python3 -m ...`, onboarding, --install-aliases
torrent_search/
├── base.py          # SearchResult, Source enum, BaseScraper, ScraperResult
├── config.py        # URLs, credentials, rate limits, limits
├── filters.py       # FilterEngine + FilterSpec
├── normalizer.py    # size/magnet/hash parsing helpers
├── cli.py           # async CLI entry point (search, --download, --show)
├── state.py         # saves/loads the numbered result index
├── download.py      # hands magnets to BiglyBT / any --client
└── scrapers/        # 16 site scrapers (tpb, yts, x1337, limetorrents, torlock,
                     #   torrenting, eztvx, extto, katcr, torrentparadise,
                     #   rutracker, yggtorrent, zamunda, maxitorrent, bitru, gimmepeers)
```

See `SESSION_KNOWLEDGE.md` for the full research session (site counts, live-domain checks, tooling analysis, bugs fixed). See `work_trace_log.md` for architecture decisions.
