#!/bin/bash
# Verify a release bundle offline, then flash one variant through the Raspberry Pi GPIO programmer.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

usage() {
  echo "usage: flash.sh [-y] <release-dir> <standard|mini|l3v7>" >&2
  exit 2
}

assume_yes=0
if [ "${1:-}" = "-y" ]; then
  assume_yes=1
  shift
fi
[ "$#" -eq 2 ] || usage
release=$1
variant=$2
case $variant in
  standard | mini | l3v7) ;;
  *) usage ;;
esac

load_bundle "$release" "$variant"

select_avrdude
build_conf

echo "release : $name (software $software, firmware revision $revision)"
echo "variant : $variant (product ID $product_id)"
echo "image   : $hex"
echo "sha256  : $(sha256sum "$hex" | cut -d' ' -f1)"
echo "Chip erase wipes flash AND EEPROM: settings return to defaults and the RTC offset"
echo "(register 37) is reset. Fuses are not changed."

if [ "$assume_yes" -ne 1 ]; then
  read -r -p "Type '$variant' to flash: " reply || reply=
  [ "$reply" = "$variant" ] || die "aborted; nothing was flashed"
fi

# Writing flash erases the chip first; avrdude reads the flash back and compares it.
run_avrdude -U "flash:w:$hex:i"

printf 'Flashed. With the board back on its host Pi, expect:\n'
printf '  i2cget -y 1 0x08 0     # %s\n' "$product_id"
printf '  i2cget -y 1 0x08 12    # 0x%02x\n' "$revision"
