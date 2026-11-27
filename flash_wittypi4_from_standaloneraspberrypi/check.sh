#!/bin/bash
# Read-only link test: reads the MCU signature and fuses, writes nothing.
# With --standard/--mini/--l3v7 it also verifies the chip's flash against that variant's HEX.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

usage() {
  echo "usage: check.sh [--standard|--mini|--l3v7 [release-dir]]" >&2
  echo "  no flag = link test only; a flag also compares the flash with the newest bundle's HEX" >&2
  exit 2
}

variant=
release=
for arg in "$@"; do
  case $arg in
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
[ -z "$release" ] || [ -n "$variant" ] || usage

if [ -n "$variant" ]; then
  [ -n "$release" ] || release=$(newest_bundle)
  load_bundle "$release" "$variant"
  echo "release : $name (software $software, firmware revision $revision)"
  echo "variant : $variant (product ID $product_id)"
  echo "image   : $hex"
fi

select_avrdude
build_conf
if [ -n "$variant" ]; then
  run_avrdude -U "flash:v:$hex:i"
else
  run_avrdude
fi
