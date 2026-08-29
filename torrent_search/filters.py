"""Filter engine for torrent search results.

Applies quality, codec, size, and seeders filters to a list of SearchResults.
Since almost no public torrent site supports server-side HD/4K/HQ filtering,
this engine operates on normalized titles client-side using regex.
"""

import re
from dataclasses import dataclass, field
from .base import SearchResult

@dataclass
class FilterSpec:
    min_seeders: int = 0
    min_size_gb: float = 0.0
    max_size_gb: float = float("inf")
    qualities: list[str] = field(default_factory=list)   # '2160p', '1080p', '720p', '480p'
    codecs: list[str] = field(default_factory=list)        # 'FLAC', 'ALAC', 'MP3', 'AAC', 'DTS'
    sources: list[str] = field(default_factory=list)       # 'REMUX', 'WEB-DL', 'BLURAY', 'HDRIP', 'DVDRIP', 'CAM'
    hdr: list[str] = field(default_factory=list)           # 'HDR', 'DOLBY_VISION', 'HDR10+'
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    sources_filter: list[str] = field(default_factory=list)  # source name filter ('tpb', 'yts', ...)


class FilterEngine:
    QUALITY_PATTERNS = {
        "2160p": re.compile(r"(2160p|4k|uhd)", re.IGNORECASE),
        "1080p": re.compile(r"(1080p|fhd|full\s*hd)", re.IGNORECASE),
        "720p": re.compile(r"720p", re.IGNORECASE),
        "480p": re.compile(r"480p", re.IGNORECASE),
    }

    CODEC_PATTERNS = {
        "FLAC": re.compile(r"\bflac\b", re.IGNORECASE),
        "ALAC": re.compile(r"\balac\b", re.IGNORECASE),
        "MP3": re.compile(r"\bmp3\b|320\s*kbps", re.IGNORECASE),
        "AAC": re.compile(r"\baac\b", re.IGNORECASE),
        "DTS": re.compile(r"\bdts[-]?(hd|ma|x)?\b", re.IGNORECASE),
        "TRUEHD": re.compile(r"\btruehd\b|atmos", re.IGNORECASE),
        "OPUS": re.compile(r"\bopus\b", re.IGNORECASE),
    }

    SOURCE_PATTERNS = {
        "REMUX": re.compile(r"\bremux\b", re.IGNORECASE),
        "WEB-DL": re.compile(r"\bweb[-]?dl\b", re.IGNORECASE),
        "WEBRIP": re.compile(r"\bweb[-]?rip\b", re.IGNORECASE),
        "BLURAY": re.compile(r"\bblu[-]?ray\b", re.IGNORECASE),
        "BDRIP": re.compile(r"\bbdrip\b|brrip", re.IGNORECASE),
        "HDRIP": re.compile(r"\bhdrip\b", re.IGNORECASE),
        "DVDRIP": re.compile(r"\bdvdrip\b", re.IGNORECASE),
        "CAM": re.compile(r"\b(cam|ts|tc|hd-?ts)\b", re.IGNORECASE),
        "SCREENER": re.compile(r"\b(scr|screener)\b", re.IGNORECASE),
    }

    HDR_PATTERNS = {
        "HDR": re.compile(r"\bhdr\b|hdr10\+?", re.IGNORECASE),
        "DOLBY_VISION": re.compile(r"dolby\s*vision|\bdv\b", re.IGNORECASE),
        "HDR10+": re.compile(r"hdr10\+|hdr10", re.IGNORECASE),
    }

    AUDIO_CHANNEL_PATTERNS = {
        "5.1": re.compile(r"(5\.1|DD5\.1|DD\s*5\.1)", re.IGNORECASE),
        "7.1": re.compile(r"(7\.1|DD7\.1)", re.IGNORECASE),
        "ATMOS": re.compile(r"atmos", re.IGNORECASE),
    }

    ENCODING_PATTERNS = {
        "H264": re.compile(r"\b(h\.?264|avc|x264)\b", re.IGNORECASE),
        "H265": re.compile(r"\b(h\.?265|hevc|x265)\b", re.IGNORECASE),
        "AV1": re.compile(r"\bav1\b", re.IGNORECASE),
        "XVID": re.compile(r"\bxvid\b", re.IGNORECASE),
    }

    def _check_pattern(self, text: str, pattern_dict: dict[str, re.Pattern], allowed: list[str]) -> bool:
        if not allowed:
            return True  # no filter = pass
        for key in allowed:
            pat = pattern_dict.get(key) or pattern_dict.get(key.upper()) or pattern_dict.get(key.lower())
            if pat and pat.search(text):
                return True
        return False

    def apply(self, results: list[SearchResult], spec: FilterSpec) -> list[SearchResult]:
        filtered = []
        for r in results:
            if not self._matches(r, spec):
                continue
            filtered.append(r)
        return filtered

    def _matches(self, result: SearchResult, spec: FilterSpec) -> bool:
        # Source filter
        if spec.sources_filter and result.source.value not in spec.sources_filter:
            return False

        # Seeders
        if result.seeders < spec.min_seeders:
            return False

        # Size
        size_gb = result.size_bytes / (1024**3) if result.size_bytes > 0 else 0
        if spec.min_size_gb > 0 and size_gb < spec.min_size_gb:
            return False
        if size_gb > spec.max_size_gb:
            return False

        title = result.title

        # Quality
        if spec.qualities:
            if not self._check_pattern(title, self.QUALITY_PATTERNS, spec.qualities):
                return False

        # Codecs
        if spec.codecs:
            if not self._check_pattern(title, self.CODEC_PATTERNS, spec.codecs):
                return False

        # Sources
        if spec.sources:
            if not self._check_pattern(title, self.SOURCE_PATTERNS, spec.sources):
                return False

        # HDR
        if spec.hdr:
            if not self._check_pattern(title, self.HDR_PATTERNS, spec.hdr):
                return False

        # Must contain
        if spec.must_contain:
            if not all(re.search(p, title, re.IGNORECASE) for p in spec.must_contain):
                return False

        # Must not contain
        if spec.must_not_contain:
            if any(re.search(p, title, re.IGNORECASE) for p in spec.must_not_contain):
                return False

        return True

    def detect_quality(self, title: str) -> str:
        """Detect the highest resolution quality from a title string."""
        for q in ["2160p", "1080p", "720p", "480p"]:
            pat = self.QUALITY_PATTERNS.get(q)
            if pat and pat.search(title):
                return q
        return ""

    def detect_codecs(self, title: str) -> list[str]:
        found = []
        for name, pat in self.CODEC_PATTERNS.items():
            if pat.search(title):
                found.append(name)
        return found

    def detect_source(self, title: str) -> str:
        for name, pat in self.SOURCE_PATTERNS.items():
            if pat.search(title):
                return name
        return ""

    def sort_by_seeders(self, results: list[SearchResult], reverse: bool = True) -> list[SearchResult]:
        return sorted(results, key=lambda r: r.seeders, reverse=reverse)
