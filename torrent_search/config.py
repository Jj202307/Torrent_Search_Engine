"""Configuration and constants for torrent scrapers."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / ".cache"
SESSION_DIR = CACHE_DIR / "sessions"

# HTTP
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RETRIES = 2
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# Rate limiting (seconds between requests within a site)
RATE_LIMITS: dict[str, float] = {
    "tpb": 0.5,
    "yts": 1.0,
    "1337x": 1.5,
    "limetorrents": 1.5,
    "torlock": 1.0,
    "eztvx": 1.5,
    "extto": 1.0,
    "rutracker": 1.0,
    "yggtorrent": 1.5,
    "zamunda": 1.5,
    "maxitorrent": 1.0,
    "bitru": 1.0,
    "gimmepeers": 1.5,
    "katcr": 1.5,
    "torrentparadise": 1.0,
    "torrenting": 1.0,
}

# Credentials from environment (for login-required sites)
CREDENTIALS = {
    "rutracker": {
        "username": os.getenv("RUTRACKER_USERNAME", ""),
        "password": os.getenv("RUTRACKER_PASSWORD", ""),
    },
    "yggtorrent": {
        "username": os.getenv("YGGTORRENT_USERNAME", ""),
        "password": os.getenv("YGGTORRENT_PASSWORD", ""),
    },
    "zamunda": {
        "username": os.getenv("ZAMUNDA_USERNAME", ""),
        "password": os.getenv("ZAMUNDA_PASSWORD", ""),
    },
    "maxitorrent": {
        "username": os.getenv("MAXITORRENT_USERNAME", ""),
        "password": os.getenv("MAXITORRENT_PASSWORD", ""),
    },
    "bitru": {
        "username": os.getenv("BITRU_USERNAME", ""),
        "password": os.getenv("BITRU_PASSWORD", ""),
    },
    "gimmepeers": {
        "username": os.getenv("GIMMEPEERS_USERNAME", ""),
        "password": os.getenv("GIMMEPEERS_PASSWORD", ""),
    },
}

# Maximum results per scraper
MAX_RESULTS_PER_SOURCE = 50

# Base URLs
SITE_URLS = {
    "tpb": "https://thepiratebay.org",
    "tpb_api": "https://apibay.org",
    "yts": "https://yts.bz",
    "yts_api": "https://movies-api.accel.li/api/v2",
    "x1337": "https://1337x.to",
    "limetorrents": "https://www.limetorrents.lol",
    "torlock": "https://www.torlock.com",
    "eztvx": "https://eztvx.to",
    "extto": "https://ext.to",
    "rutracker": "https://rutracker.org",
    "yggtorrent": "https://yggtorrent.ws",
    "zamunda": "https://zamunda.net",
    "maxitorrent": "https://maxitorrent.net",
    "bitru": "https://bitru.org",
    "gimmepeers": "https://gimmepeers.com",
    "katcr": "https://katcr.co",
    "torrentparadise": "https://torrentparadise.org",
    "torrenting": "https://torrenting.com",
}
