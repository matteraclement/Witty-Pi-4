#!/bin/bash
# Short form of flash.sh: flash the newest bundle in ../release to a standard board, or --mini / --l3v7.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

usage() {
  echo "usage: updatefirmware.sh [-y] [--standard|--mini|--l3v7] [release-dir]" >&2
  echo "  no variant flag = standard board; no release-dir = newest bundle in ../release" >&2
  exit 2
}

flags=()
variant=
release=
for arg in "$@"; do
  case $arg in
    -y) flags=(-y) ;;
    --standard | --mini | --l3v7)
      [ -z "$variant" ] || usage
      variant=${arg#--}
      ;;
    -*) usage ;;
    *)
      [ -z "$release" ] || usage
      release=$arg
      ;;
  esac
done
variant=${variant:-standard}

[ -n "$release" ] || release=$(newest_bundle)

exec "$FLASH_DIR/flash.sh" "${flags[@]}" "$release" "$variant"
