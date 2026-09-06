# Bash tab completion for the Torrent Search Engine CLI.
#
# Install (one line in ~/.bashrc, adjust the path):
#   source ~/Downloads/Projects/Torrent_Search_Engine/completions/torrent_search_dl.bash
#
# Completes: flags anywhere; preset names after --rt-cat/-C; source names
# after --sources/-s; choices after --format/--sort/--client.

_torrent_search_dl() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local presets="digitizations dsd hi-res movies tv-series"
    local sources="1337x audiobookbay bitru extto eztvx gimmepeers katcr knaben limetorrents maxitorrent rutracker tpb torrenting torrentparadise torlock yggtorrent yts zamunda yourbittorrent"
    local formats="table json simple"
    local sorts="seeders size"
    local opts="-h --help -s --sources -q --quality --codec --source-type --hdr --min-seeders --min-size --max-size --must-contain --must-not-contain --limit --page --sort -C --rt-cat -F --rt-forum -P --rt-pages -L --rt-list-forums --format --timeout --no-progress --list-sources --download --show --client --no-hints"

    case "$prev" in
        -C|--rt-cat)   COMPREPLY=( $(compgen -W "$presets" -- "$cur") ); return 0 ;;
        -s|--sources)  COMPREPLY=( $(compgen -W "$sources" -- "$cur") ); return 0 ;;
        --format)      COMPREPLY=( $(compgen -W "$formats" -- "$cur") ); return 0 ;;
        --sort)        COMPREPLY=( $(compgen -W "$sorts" -- "$cur") );   return 0 ;;
        --client)      COMPREPLY=( $(compgen -W "biglybt" -- "$cur") );  return 0 ;;
    esac

    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    return 0
}

# torrent_search_dl is the bash alias installed by torrent_search.sh
# --install-aliases; torrent-search is the pip-installed entry point.
complete -F _torrent_search_dl torrent_search_dl torrent-search
