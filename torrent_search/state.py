"""Persist the last search's results so a followup command can download from them."""

import json
import time
from dataclasses import asdict
from pathlib import Path

from .base import SearchResult, Source
from .config import SESSION_DIR

STATE_FILE = SESSION_DIR / "last_results.json"


def save_results(query: str, results: list[SearchResult]) -> Path:
    """Write the displayed results to the state index. Returns the state file path."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "results": [
            {**asdict(r), "source": r.source.value}
            for r in results
        ],
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return STATE_FILE


def load_results() -> tuple[str, list[SearchResult]]:
    """Load the last saved search. Returns (query, results)."""
    if not STATE_FILE.exists():
        raise FileNotFoundError(
            f"No saved results at {STATE_FILE}. Run a search first, "
            "e.g. `torrent-search 'your query'`."
        )
    payload = json.loads(STATE_FILE.read_text())
    results = []
    for d in payload.get("results", []):
        d = dict(d)
        d["source"] = Source(d["source"])
        results.append(SearchResult(**d))
    return payload.get("query", ""), results
