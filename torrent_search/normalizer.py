"""Normalizer helpers for parsing size strings, extracting magnets, etc."""

import re

SIZE_REGEX = re.compile(
    r"(?:size[:\s]*)?(?P<value>[\d,.]+)\s*(?P<unit>(?:Gi?B|Ti?B|Mi?B|Ki?B|B))\b",
    re.IGNORECASE,
)

MAGNET_REGEX = re.compile(r"(magnet:\?xt=urn:btih:[a-fA-F0-9]{32,40}[^\s\"'<>]*)")
HASH_REGEX = re.compile(r"\b([a-fA-F0-9]{40})\b")


def parse_size(text: str) -> int:
    """Parse a human-readable size string (e.g. '9.8 GB', '1.2 MiB') into bytes."""
    m = SIZE_REGEX.search(text)
    if not m:
        return 0
    value = float(m.group("value").replace(",", ""))
    unit = m.group("unit").upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024**2,
        "MIB": 1024**2,
        "GB": 1024**3,
        "GIB": 1024**3,
        "TB": 1024**4,
        "TIB": 1024**4,
    }
    return int(value * multipliers.get(unit, 1))


def parse_seeders_leechers(text: str) -> tuple[int, int]:
    """Extract seeders and leechers counts from text containing two numbers."""
    nums = re.findall(r"\d[\d,]*", text)
    if len(nums) >= 2:
        return int(nums[0].replace(",", "")), int(nums[1].replace(",", ""))
    if len(nums) == 1:
        return int(nums[0].replace(",", "")), 0
    return 0, 0


def extract_magnet(text: str) -> str:
    """Extract a magnet URI from text."""
    m = MAGNET_REGEX.search(text)
    return m.group(1) if m else ""


def extract_info_hash(text: str) -> str:
    """Extract a 40-char hex info hash from text."""
    m = HASH_REGEX.search(text)
    return m.group(1) if m else ""


def to_int(text: str) -> int:
    """Convert a numeric string (possibly with commas) to int, returning 0 on failure."""
    try:
        return int(text.replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return 0
