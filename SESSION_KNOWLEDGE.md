# Session Knowledge — pointer

This file used to mix a dated build log with durable operational reference. It is now split:

- **CHANGELOG.md** — dated change history (2026-08-01, 2026-09-06, 2026-09-21; changelog.md merged into it).
- **Handover_Torrent_Search_Engine_09_21_01:28.md** — current-state operational reference (handover.md is SUPERSEDED).

Runtime: FlareSolverr docker sidecar is a hard dependency for rutracker/extto (docker `flaresolverr`, :8191); successful solves persist to a replay cache in `~/.cache/torrent_search/` and replay in ~1-2s (see handover).

Architecture decisions and day-by-day working notes: work_trace_log.md.
