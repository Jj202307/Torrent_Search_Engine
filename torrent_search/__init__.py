"""Torrent Search Engine — multi-source search with parallel scrapers and filtering."""

from .base import SearchResult, Source, BaseScraper, ScraperResult
from .filters import FilterEngine, FilterSpec
from .normalizer import parse_size, extract_magnet, extract_info_hash

__version__ = "0.1.0"
__all__ = [
    "SearchResult",
    "Source",
    "BaseScraper",
    "ScraperResult",
    "FilterEngine",
    "FilterSpec",
    "parse_size",
    "extract_magnet",
    "extract_info_hash",
]
