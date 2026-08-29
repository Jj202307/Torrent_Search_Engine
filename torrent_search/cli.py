import asyncio
import argparse
import sys
from typing import Any
from .filters import FilterEngine, FilterSpec
from .base import SearchResult, Source
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

async def search_single(source_name: str, query: str, **kwargs):
    """Search one source, return ScraperResult."""
    cls = SCRAPER_CLASSES.get(source_name)
    if cls is None:
        from .base import ScraperResult
        return ScraperResult(source=Source(source_name), error="Scraper not implemented", success=False)
    try:
        scraper = cls()
        results = await scraper.search(query, **kwargs)
        await scraper.close()
        from .base import ScraperResult
        return ScraperResult(source=scraper.source, results=results)
    except Exception as e:
        from .base import ScraperResult
        return ScraperResult(source=Source(source_name), error=str(e), success=False)

async def search_all(query: str, sources: list[str], **kwargs):
    """Search multiple sources in parallel."""
    tasks = [search_single(s, query, **kwargs) for s in sources]
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
    print("Download these:  torrent-search --download 1,3,4")
    print("Re-list saved:   torrent-search --show")
    print("All options:     torrent-search --help")
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

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="torrent-search",
        description="Multi-source torrent search with filtering",
    )
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--sources", "-s", help="Comma-separated source names (default: all)")
    parser.add_argument("--min-seeders", type=int, default=0, help="Minimum seeders")
    parser.add_argument("--quality", "-q", action="append", default=[], help="Quality: 2160p, 1080p, 720p, 480p")
    parser.add_argument("--codec", action="append", default=[], help="Codec: FLAC, AAC, DTS, etc.")
    parser.add_argument("--source-type", action="append", default=[], dest="source_types", help="Source type: REMUX, WEB-DL, BLURAY, etc.")
    parser.add_argument("--hdr", action="append", default=[], help="HDR: HDR, DOLBY_VISION, HDR10+")
    parser.add_argument("--min-size", type=float, default=0.0, help="Minimum size in GB")
    parser.add_argument("--max-size", type=float, default=float("inf"), help="Maximum size in GB")
    parser.add_argument("--must-contain", action="append", default=[], help="Keyword that must be in title")
    parser.add_argument("--must-not-contain", action="append", default=[], help="Keyword that must NOT be in title")
    parser.add_argument("--limit", type=int, default=50, help="Max total results")
    parser.add_argument("--sort", choices=["seeders", "size"], default="seeders", help="Sort results by")
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
            report = download_results(picked, args.client)
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        print_download_summary(report, args.client)
        return

    if not args.query:
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

    # Run search
    async def _run():
        all_source_results = await asyncio.wait_for(
            search_all(args.query, sources),
            timeout=args.timeout,
        )
        # Collect results
        results: list[SearchResult] = []
        for sr in all_source_results:
            if sr.success and sr.results:
                results.extend(sr.results)
        
        # Apply filters
        results = filter_engine.apply(results, filter_spec)
        
        # Sort
        if args.sort == "seeders":
            results = filter_engine.sort_by_seeders(results, reverse=True)
        elif args.sort == "size":
            results.sort(key=lambda r: r.size_bytes, reverse=True)
        
        # Limit
        results = results[:args.limit]

        # Save as the downloadable index, then display or download
        save_results(args.query, results)
        if args.download:
            try:
                indices = parse_index_spec(args.download, len(results))
            except ValueError as e:
                print(e, file=sys.stderr)
                sys.exit(1)
            picked = [results[i - 1] for i in indices]
            try:
                report = download_results(picked, args.client)
            except FileNotFoundError as e:
                print(e, file=sys.stderr)
                sys.exit(1)
            print_download_summary(report, args.client)
        else:
            display_results(results, args.format, hints=not args.no_hints)

    try:
        asyncio.run(_run())
    except asyncio.TimeoutError:
        print("Search timed out. Try increasing --timeout or reducing --sources.", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nSearch cancelled.", file=sys.stderr)


if __name__ == "__main__":
    main()
