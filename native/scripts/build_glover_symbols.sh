#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 3 ]]; then echo 'Usage: build_glover_symbols.sh native-root canonical-rom report-path' >&2; exit 2; fi
root="$1"; rom="$2"; output="$3"
[[ -f "$rom" ]] || { echo 'Private canonical ROM not found' >&2; exit 2; }
[[ -f "$root/extern/n64sym/Makefile" ]] || { echo 'Pinned n64sym dependency missing' >&2; exit 2; }
mkdir -p "$(dirname "$output")"
cd "$root/extern/n64sym"
# The checked dependency patch keeps ambiguous matches and reports true sizes.
make -j2 n64sym
[[ -x bin/n64sym ]] || { echo 'n64sym executable was not produced' >&2; exit 3; }
tmp="${output}.partial"
rm -f "$tmp"
# Explicit displacement is critical: Glover loads at 80100000, not 80000400.
./bin/n64sym "$rom" -s -t -h 0x800ff000 -f default -o "$tmp"
[[ -s "$tmp" ]] || { echo 'Symbol scan returned no records' >&2; exit 4; }
mv -f "$tmp" "$output"
echo "Glover SDK signature report: $output"
