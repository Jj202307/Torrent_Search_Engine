import asyncio
import argparse
import sys
from typing import Any
from .filters import FilterEngine, FilterSpec
from .base import SearchResult, Source
from .config import set_max_results_per_source
from .download import download_results, print_download_summary
from .state import load_results, save_results

# Import all scraper classes, catching ImportError for any not yet written
SCRAPER_CLASSES = {}
_scraper_modules = {
    "tpb": ("tpb", "TPBScraper"),
    "yts": ("yts", "YTSScraper"),
    "1337x": ("x1337", "X1337Scraper"),
    "limetorrents": ("limetorrents", "LimeTorrentsScraper"),
    "torlock": ("torlock", "TorLockScraper"),
    "eztvx": ("eztvx", "EZTVXScraper"),
    "extto": ("extto", "EXTtoScraper"),
    "rutracker": ("rutracker", "RuTrackerScraper"),
    "yggtorrent": ("yggtorrent", "YggTorrentScraper"),
    "zamunda": ("zamunda", "ZamundaScraper"),
    "maxitorrent": ("maxitorrent", "MaxitorrentScraper"),
    "bitru": ("bitru", "BitRuScraper"),
    "gimmepeers": ("gimmepeers", "GimmePeersScraper"),
    "katcr": ("katcr", "KatCRScraper"),
    "torrentparadise": ("torrentparadise", "TorrentParadiseScraper"),
    "torrenting": ("torrenting", "TorrentingScraper"),
    "yourbittorrent": ("yourbittorrent", "YourBittorrentScraper"),
    "audiobookbay": ("audiobookbay", "AudioBookBayScraper"),
    "knaben": ("knaben", "KnabenScraper"),
}

for name, (module_name, class_name) in _scraper_modules.items():
    try:
        mod = __import__(f"torrent_search.scrapers.{module_name}", fromlist=[class_name])
        cls = getattr(mod, class_name)
        SCRAPER_CLASSES[name] = cls
    except ImportError:
        pass  # module not yet written, skip

def list_sources():
    """Print available sources."""
    available = sorted(SCRAPER_CLASSES.keys())
    all_sources = sorted(_scraper_modules.keys())
    for s in all_sources:
        status = "✓" if s in SCRAPER_CLASSES else "✗ (not implemented)"
        print(f"  {s:25} {status}")

def _rutracker_module():
    """Lazy import so a missing curl_cffi never breaks the rest of the CLI."""
    try:
        from .scrapers import rutracker as rt
        return rt
    except Exception:
        return None

def print_rutracker_forums():
    """List presets and forum ids with descriptive names (--rt-list-forums)."""
    rt = _rutracker_module()
    if rt is None:
        print("rutracker scraper unavailable (is curl_cffi installed?).", file=sys.stderr)
        sys.exit(1)
    print("RuTracker category presets — use --rt-cat KEY (with -s rutracker):")
    for key in sorted(rt.FORUM_PRESETS):
        preset = rt.FORUM_PRESETS[key]
        print(f"  {key:15} {preset['label']}  ({len(preset['forums'])} forums)")
    print("\nRuTracker forums — use --rt-forum ID (repeatable, combinable with a query):")
    for branch, forums in rt.FORUM_DIRECTORY:
        print(f"\n  {branch}:")
        for fid, name in forums:
            print(f"    {fid:<6} {name}")

async def search_single(source_name: str, query: str, timeout: float | None = None, **kwargs):
    """Search one source, return ScraperResult.

    The timeout is per source: one slow site cancels only itself instead
    of taking the whole gather (and every already-finished source) down.
    """
    cls = SCRAPER_CLASSES.get(source_name)
    if cls is None:
        from .base import ScraperResult
        return ScraperResult(source=Source(source_name), error="Scraper not implemented", success=False)
    try:
        scraper = cls()
        try:
            results = await asyncio.wait_for(scraper.search(query, **kwargs), timeout=timeout)
        finally:
            await scraper.close()
        from .base import ScraperResult
        return ScraperResult(source=scraper.source, results=results)
    except Exception as e:
        from .base import ScraperResult
        return ScraperResult(source=Source(source_name), error=str(e), success=False)

async def search_all(query: str, sources: list[str], timeout: float | None = None, **kwargs):
    """Search multiple sources in parallel."""
    tasks = [search_single(s, query, timeout=timeout, **kwargs) for s in sources]
    return await asyncio.gather(*tasks)

def format_table(results: list[SearchResult]):
    """Format results as a rich table."""
    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title="Torrent Search Results")
    table.add_column("#", justify="right", style="dim", min_width=3)
    table.add_column("Source", style="cyan", min_width=12)
    table.add_column("Title", style="white", min_width=50)
    table.add_column("Size", style="green", justify="right", min_width=10)
    table.add_column("Seeders", style="yellow", justify="right", min_width=8)
    table.add_column("Leechers", style="red", justify="right", min_width=8)
    
    for i, r in enumerate(results, start=1):
        size_str = f"{r.size_bytes / 1024**3:.2f} GB" if r.size_bytes > 0 else "?"
        table.add_row(
            str(i),
            r.source.value,
            r.title[:100],
            size_str,
            str(r.seeders),
            str(r.leechers),
        )
    console.print(table)

def format_json(results: list[SearchResult]):
    """Format results as JSON."""
    import json
    data = [
        {
            "source": r.source.value,
            "title": r.title,
            "size_bytes": r.size_bytes,
            "seeders": r.seeders,
            "leechers": r.leechers,
            "magnet": r.magnet,
            "torrent_url": r.torrent_url,
            "info_hash": r.info_hash,
            "uploader": r.uploader,
            "added": r.added,
            "page_url": r.page_url,
        }
        for r in results
    ]
    print(json.dumps(data, indent=2, ensure_ascii=False))

def format_simple(results: list[SearchResult]):
    """Format results as simple text lines with index numbers."""
    for i, r in enumerate(results, start=1):
        size_str = f"{r.size_bytes / 1024**3:.2f} GB" if r.size_bytes > 0 else "?"
        print(f"{i:>3} [{r.source.value:15}] S:{r.seeders:4} L:{r.leechers:4} {size_str:>10}  {r.title}")

def print_hints(show: bool = True):
    """Usage examples shown under results so the next command is obvious."""
    if not show:
        return
    print()
    print("----------------------------------------------------------")
    print("Download these:  torrent_search_dl --download 1,3,4")
    print("Re-list saved:   torrent_search_dl --show")
    print("All options:     torrent_search_dl --help")
    print("----------------------------------------------------------")

def display_results(results: list[SearchResult], fmt: str = "table", hints: bool = True):
    if fmt == "json":
        format_json(results)
    elif fmt == "simple":
        format_simple(results)
    else:
        format_table(results)
    if fmt != "json":
        print_hints(hints)

def parse_index_spec(spec: str, total: int) -> list[int]:
    """Parse '1,3-5,7' or 'all' into sorted 1-based indices within 1..total."""
    spec = (spec or "").strip().lower()
    if not spec:
        raise ValueError("Empty --download spec. Use e.g. 1,3-5 or all.")
    if spec == "all":
        return list(range(1, total + 1))
    indices: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            start, end = int(a), int(b) if b else total
        else:
            start = end = int(part)
        if start < 1 or end > total or start > end:
            raise ValueError(
                f"Index {part!r} out of range; results are numbered 1-{total}."
            )
        indices.update(range(start, end + 1))
    return sorted(indices)

_HELP_EPILOG = """\
rutracker flags (server-side scoping; use with -s rutracker):
  -C PRESET   scope the search to a named forum preset:
              hi-res         Hi-Res lossless music (16 forums)
              digitizations  rips of analog media (16 forums)
              dsd            DSD everywhere = hi-res + digitizations (32 forums)
              movies         foreign & Russian cinema, DVD/HD/UHD, cartoons,
                             anime, theater, 3D (106 forums)
              tv-series      Russian, foreign SD/HD/UHD incl. US & Canada,
                             LatAm/Turkey/India, Asian (78 forums)
  -F ID       restrict to specific forum ids, repeatable (e.g. -F 1755 -F 1757;
              see -L for ids with descriptive names). Usable alone (no query)
              to browse a forum's latest posts
  -P N        fetch N server pages of 50 rows (max 10 = the server's 500-row
              hard cap; 5s spacing protects the Cloudflare clearance);
              replaces --page/--limit in rutracker mode
  -L          list presets and all forum ids with descriptive names, then exit
  tip: for SEARCHES, scope with one or two forum ids (-F) — the server
  silently loses matches when a query is combined with many forums (a whole
  preset). Presets (-C) are for no-query browsing: music presets mix
  normally; movies / tv-series hit the 500-row cap and page forum-by-forum.

examples:
  # search one forum: 'dune' in foreign-UHD movies (query + few ids = reliable)
  torrent_search_dl 'dune' -s rutracker -F 1457 -q 2160p

  # TV series: 'severance' in the US/Canada HD forum (find ids with -L)
  torrent_search_dl 'severance' -s rutracker -F 266

  # newest UHD movies, client-side quality filter (no query = browse)
  torrent_search_dl -s rutracker -F 1457 -P 2 -q 2160p

  # browse newest posts in the Hi-Res music preset (3 pages of 50)
  torrent_search_dl -s rutracker -C hi-res -P 3

  # DSD material everywhere, then keep only DSD/SACD/DSF/DFF titles
  torrent_search_dl 'DSD' -s rutracker -C dsd --codec dsd

  # two specific music forums by id, deep-paged
  torrent_search_dl 'flac' -s rutracker -F 1755 -F 1756 -P 2

  # browse a single forum with no query (pattern: any id from -L; -P N = N x 50)
  torrent_search_dl -s rutracker -F 1457 -P 2

  # movies in UHD (4K) and HD, browsed
  torrent_search_dl -s rutracker -F 1457 -F 271        # foreign + art-house UHD
  torrent_search_dl -s rutracker -F 313 -F 312         # foreign + Russian HD

  # keep up with new releases: 2026 films + 2021-2025 + airing shows
  torrent_search_dl -s rutracker -F 252 -F 1950 -F 1803 -P 2

  # hi-res / digitized music by genre
  torrent_search_dl -s rutracker -F 1163 -P 2          # Dolby Atmos
  torrent_search_dl -s rutracker -F 1756               # digitized foreign rock
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="torrent_search_dl",
        description=(
            "Multi-source torrent search with filtering. Exclusion with single "
            "quotes and ! prefix (ex. '!480p') works the same for --quality, "
            "--codec, --source-type and --hdr"
        ),
        epilog=_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--sources", "-s", help="Comma-separated source names (default: all)")
    parser.add_argument("--min-seeders", type=int, default=0, help="Minimum seeders")
    parser.add_argument("--quality", "-q", action="append", default=[], help="Quality: 2160p/4k/uhd, 1080p/fhd, 720p, 480p; Exclude specific quality for ex. 480p, by using Single quotes and ! prefix like '!480p'")
    parser.add_argument("--codec", action="append", default=[], help="Codec: FLAC, DSD (matches DSD/SACD/DSF/DFF), AAC, DTS, etc.; '!value' (quoted) excludes")
    parser.add_argument("--source-type", action="append", default=[], dest="source_types", help="Source type: REMUX, WEB-DL, BLURAY, etc.; '!value' (quoted) excludes")
    parser.add_argument("--hdr", action="append", default=[], help="HDR: HDR, DOLBY_VISION, HDR10+; '!value' (quoted) excludes")
    parser.add_argument("--min-size", type=float, default=0.0, help="Minimum size in GB")
    parser.add_argument("--max-size", type=float, default=float("inf"), help="Maximum size in GB")
    parser.add_argument("--must-contain", action="append", default=[], help="Keyword that must be in title")
    parser.add_argument("--must-not-contain", action="append", default=[], help="Keyword that must NOT be in title")
    parser.add_argument("--limit", type=int, default=50, help="Results per page (page size)")
    parser.add_argument("--page", type=int, default=1, help="Result page to display (2 = next --limit results)")
    parser.add_argument("--sort", choices=["seeders", "size"], default="seeders", help="Sort results by")
    rt = _rutracker_module()
    rt_choices = sorted(rt.FORUM_PRESETS) if rt else ["digitizations", "dsd", "hi-res", "movies", "tv-series"]
    if rt:
        rt_cat_help = ("RuTracker only (use with -s rutracker): scope the search server-side to a named "
                       "preset — " + "; ".join(f"{k} = {rt.FORUM_PRESETS[k]['label']}" for k in rt_choices)
                       + ". Usable alone (no query) to browse latest posts")
    else:
        rt_cat_help = "RuTracker only: scope the search server-side (hi-res / digitizations / dsd / movies / tv-series)"
    parser.add_argument("--rt-cat", "-C", dest="rt_cat", choices=rt_choices, metavar="PRESET", help=rt_cat_help)
    parser.add_argument("--rt-forum", "-F", dest="rt_forum", action="append", type=int, metavar="ID",
                        help="RuTracker only: forum id, repeatable (e.g. --rt-forum 1755 --rt-forum 1757). "
                             "Usable alone (no query) to browse a forum's latest posts. "
                             "Run --rt-list-forums to see ids with descriptive names")
    parser.add_argument("--rt-pages", "-P", dest="rt_pages", type=int, default=1, metavar="N",
                        help="RuTracker only: server pages to fetch, 50 rows each (max 10 = the server's "
                             "500-row hard cap; 5s spacing protects the Cloudflare clearance). "
                             "This is the paging mechanism in --rt mode — --page/--limit are ignored there")
    parser.add_argument("--rt-list-forums", "-L", dest="rt_list_forums", action="store_true",
                        help="List RuTracker presets and forum ids with descriptive names, then exit")
    parser.add_argument("--format", choices=["table", "json", "simple"], default="table", help="Output format")
    parser.add_argument("--timeout", type=int, default=30, help="Total search timeout in seconds")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bar")
    parser.add_argument("--list-sources", action="store_true", help="List available sources and exit")
    parser.add_argument("--download", metavar="SPEC", help="Download results by index (e.g. 1,3-5 or all). Without a query, uses the last saved results.")
    parser.add_argument("--show", action="store_true", help="Re-print the last saved results with their indices.")
    parser.add_argument("--client", default="biglybt", help="BitTorrent client to hand magnets to (default: biglybt).")
    parser.add_argument("--no-hints", action="store_true", help="Do not print usage examples under results.")
    return parser

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.page < 1:
        parser.error("--page must be >= 1")
    if args.rt_pages < 1:
        parser.error("--rt-pages must be >= 1")

    if args.rt_list_forums:
        print_rutracker_forums()
        return

    if args.list_sources:
        print("Available sources:")
        list_sources()
        return

    if args.show:
        try:
            query, saved = load_results()
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        if query:
            print(f"Saved results for: {query}\n")
        display_results(saved, args.format, hints=not args.no_hints)
        return

    if args.download and not args.query:
        try:
            _, saved = load_results()
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        try:
            indices = parse_index_spec(args.download, len(saved))
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        picked = [saved[i - 1] for i in indices]
        try:
            report = asyncio.run(download_results(picked, args.client))
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        print_download_summary(report, args.client)
        return

    if not args.query and not (args.rt_cat or args.rt_forum):
        parser.print_help()
        return

    # Determine sources
    if args.sources:
        sources = [s.strip() for s in args.sources.split(",")]
        sources = [s for s in sources if s in SCRAPER_CLASSES]
    else:
        sources = list(SCRAPER_CLASSES.keys())

    if not sources:
        print("No available sources to search.", file=sys.stderr)
        return

    # RuTracker scoping kwargs — flow to scraper.search(**kwargs); other
    # scrapers ignore them. In rt mode --rt-pages is the paging mechanism,
    # so the client-side --page/--limit slice is skipped entirely.
    rt_kwargs: dict[str, Any] = {}
    if args.rt_cat:
        rt_kwargs["category"] = args.rt_cat
    if args.rt_forum:
        rt_kwargs["forums"] = args.rt_forum
    if args.rt_pages > 1:
        rt_kwargs["pages"] = args.rt_pages
    if rt_kwargs and "rutracker" not in sources:
        print("Warning: --rt-* options only affect the rutracker source.", file=sys.stderr)

    # Build filter spec
    filter_engine = FilterEngine()
    filter_spec = FilterSpec(
        min_seeders=args.min_seeders,
        min_size_gb=args.min_size,
        max_size_gb=args.max_size,
        qualities=args.quality,
        codecs=args.codec,
        sources=args.source_types,
        hdr=args.hdr,
        must_contain=args.must_contain,
        must_not_contain=args.must_not_contain,
    )

    # Deep pages need more than the default per-source cap to have anything
    # to slice on single-source searches. 50 = rutracker rows per server page.
    if args.page > 1 or args.rt_pages > 1:
        set_max_results_per_source(max(args.page * args.limit, args.rt_pages * 50))

    # Per-source timeout; rt deep paging needs room for its 5s page gaps.
    timeout_s = max(args.timeout, args.rt_pages * 8)

    # Run search
    async def _run():
        all_source_results = await search_all(args.query or "", sources, timeout=timeout_s, **rt_kwargs)
        # Collect results
        results: list[SearchResult] = []
        for sr in all_source_results:
            if sr.success and sr.results:
                results.extend(sr.results)
            elif not sr.success:
                print(f"  {sr.source.value}: search failed — {sr.error}", file=sys.stderr)

        # Apply filters
        results = filter_engine.apply(results, filter_spec)

        # Sort
        if args.sort == "seeders":
            results = filter_engine.sort_by_seeders(results, reverse=True)
        elif args.sort == "size":
            results.sort(key=lambda r: r.size_bytes, reverse=True)

        # Limit (page-aware slice) — skipped in rt mode, where --rt-pages
        # already paged server-side and all fetched rows are the result.
        if not rt_kwargs:
            start = (args.page - 1) * args.limit
            if start >= len(results):
                print(f"Page {args.page} starts past the {len(results)} collected results — nothing to show.",
                      file=sys.stderr)
            results = results[start:start + args.limit]

        # Save as the downloadable index, then display or download
        save_results(args.query or (args.rt_cat or "rutracker browse"), results)
        if args.download:
            try:
                indices = parse_index_spec(args.download, len(results))
            except ValueError as e:
                print(e, file=sys.stderr)
                sys.exit(1)
            picked = [results[i - 1] for i in indices]
            try:
                report = await download_results(picked, args.client)
            except FileNotFoundError as e:
                print(e, file=sys.stderr)
                sys.exit(1)
            print_download_summary(report, args.client)
        else:
            display_results(results, args.format, hints=not args.no_hints)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nSearch cancelled.", file=sys.stderr)


if __name__ == "__main__":
    main()
