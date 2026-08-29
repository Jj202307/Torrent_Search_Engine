"""Base classes and types for torrent search scrapers."""

from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from typing import Optional

class Source(str, Enum):
    TPB = "tpb"
    YTS = "yts"
    X1337 = "1337x"
    LIMETORRENTS = "limetorrents"
    TORLOCK = "torlock"
    EZTVX = "eztvx"
    EXTTO = "extto"
    RUTRACKER = "rutracker"
    YGGTORRENT = "yggtorrent"
    ZAMUNDA = "zamunda"
    MAXITORRENT = "maxitorrent"
    BITRU = "bitru"
    GIMMEPEERS = "gimmepeers"
    KATCR = "katcr"
    TORRENTPARADISE = "torrentparadise"
    TORRENTING = "torrenting"

@dataclass
class SearchResult:
    title: str
    source: Source
    category: str = ""
    size_bytes: int = 0
    seeders: int = 0
    leechers: int = 0
    magnet: str = ""
    torrent_url: str = ""
    info_hash: str = ""
    added: str = ""
    uploader: str = ""
    page_url: str = ""

@dataclass
class ScraperResult:
    """Aggregate result from one scraper execution."""
    source: Source
    results: list[SearchResult] = field(default_factory=list)
    error: str = ""
    success: bool = True

class BaseScraper(ABC):
    source: Source

    @abstractmethod
    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        """Execute a search and return normalized results."""
        ...

    @abstractmethod
    async def alive(self) -> bool:
        """Check if the site is reachable."""
        ...
