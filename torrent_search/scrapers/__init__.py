"""Scrapers for individual torrent sites."""

from .tpb import TPBScraper
from .yts import YTSScraper
from .x1337 import X1337Scraper
from .limetorrents import LimeTorrentsScraper
from .torlock import TorLockScraper
from .torrenting import TorrentingScraper
from .eztvx import EZTVXScraper
from .extto import EXTtoScraper
from .katcr import KatCRScraper
from .torrentparadise import TorrentParadiseScraper
from .rutracker import RuTrackerScraper
from .yggtorrent import YggTorrentScraper
from .zamunda import ZamundaScraper
from .maxitorrent import MaxitorrentScraper
from .bitru import BitRuScraper
from .gimmepeers import GimmePeersScraper

__all__ = [
    "TPBScraper",
    "YTSScraper",
    "X1337Scraper",
    "LimeTorrentsScraper",
    "TorLockScraper",
    "TorrentingScraper",
    "EZTVXScraper",
    "EXTtoScraper",
    "KatCRScraper",
    "TorrentParadiseScraper",
    "RuTrackerScraper",
    "YggTorrentScraper",
    "ZamundaScraper",
    "MaxitorrentScraper",
    "BitRuScraper",
    "GimmePeersScraper",
]
