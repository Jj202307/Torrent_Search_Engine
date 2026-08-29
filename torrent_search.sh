#!/usr/bin/env bash
#
# torrent_search.sh - launcher + onboarding for the torrent search/download CLI.
#
#   ./torrent_search.sh "query" [options]   -> search (results are saved)
#   ./torrent_search.sh --download 1,3-5,7  -> open those magnets in BiglyBT
#   ./torrent_search.sh --show              -> re-print the saved index
#   ./torrent_search.sh --help              -> all search flags
#   ./torrent_search.sh --install-aliases   -> add `torrent_search_dl` aliases to ~/.bashrc
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="${HOME}/.bashrc"

onboarding() {
  cat <<'EOF'
Torrent Search Engine - one tool for search and download.

  Search (results are numbered and saved for later):
    torrent_search_dl "your query" [options]
      e.g.  torrent_search_dl "dune" --quality 2160p --min-seeders 10

  Download numbered results into BiglyBT:
    torrent_search_dl --download 1,3-5,7
    torrent_search_dl --download all

  Re-print the last saved results:
    torrent_search_dl --show

  See every search flag:
    torrent_search_dl --help

  First-time setup (adds the two aliases above to ~/.bashrc):
    ./torrent_search.sh --install-aliases
    then run:  source ~/.bashrc

  Full docs:  HowToUse.md  (next to this script)
EOF
}

install_aliases() {
  local line1 line2 tmp
  line1="alias torrent_search_dl='bash ${SCRIPT_DIR}/torrent_search.sh'"
  line2="alias torrent_search_dl_howto='bash ${SCRIPT_DIR}/torrent_search.sh --help'"
  tmp="$(mktemp)"
  grep -v '^alias torrent_search_dl=' "$BASHRC" 2>/dev/null \
    | grep -v '^alias torrent_search_dl_howto=' \
    > "$tmp" || true
  printf '\n# Torrent Search Engine aliases\n%s\n%s\n' "$line1" "$line2" >> "$tmp"
  cp "$tmp" "$BASHRC"
  rm -f "$tmp"
  echo "Added to ${BASHRC}:"
  echo "  $line1"
  echo "  $line2"
  echo "Restart your shell or run: source ${BASHRC}"
}

run_python() {
  local py=python3
  if [[ -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
    py="${SCRIPT_DIR}/.venv/bin/python"
  fi
  PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" exec "$py" -m torrent_search.cli "$@"
}

case "${1:-}" in
  --install-aliases)
    install_aliases
    ;;
  "")
    onboarding
    ;;
  *)
    run_python "$@"
    ;;
esac
