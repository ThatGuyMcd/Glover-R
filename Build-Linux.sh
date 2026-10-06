#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NATIVE="$ROOT/build/native-src"
if [[ ! -f "$NATIVE/Build-Linux.sh" || ! -f "$NATIVE/generated/glover-codegen.json" ]]; then
  echo 'Run the Windows ONE-CLICK-BUILD.cmd through CPU/RSP generation first.' >&2
  echo 'This helper packages the prepared shared game sources; it does not generate them.' >&2
  exit 1
fi
exec bash "$NATIVE/Build-Linux.sh" "$@" --output-dir "$ROOT/dist"
