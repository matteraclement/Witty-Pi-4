# shellcheck shell=bash
# Shared by check.sh and flash.sh: avrdude over the Raspberry Pi GPIO programmer.

FLASH_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PART=attiny841
PROGRAMMER=RasPi

die() {
  echo "error: $*" >&2
  exit 1
}

# The linuxgpio programmer exports sysfs GPIOs, which needs root.
# AVRDUDE_CMD overrides the whole command (used by the tests).
select_avrdude() {
  if [ -n "${AVRDUDE_CMD:-}" ]; then
    read -r -a AVRDUDE <<<"$AVRDUDE_CMD"
  elif [ "$(id -u)" -eq 0 ]; then
    AVRDUDE=(avrdude)
  else
    AVRDUDE=(sudo avrdude)
  fi
  command -v "${AVRDUDE[@]: -1}" >/dev/null || die "${AVRDUDE[*]: -1} not found; install avrdude"
}

# avrdude -C replaces the system config, so append the RasPi programmer to a copy of it.
build_conf() {
  local base=${AVRDUDE_BASE_CONF:-/etc/avrdude.conf}
  [ -r "$base" ] || die "cannot read $base (set AVRDUDE_BASE_CONF)"
  WORK_DIR=$(mktemp -d)
  trap 'rm -rf "$WORK_DIR"' EXIT
  CONF=$WORK_DIR/avrdude_gpio.conf
  cat "$base" "$FLASH_DIR/raspi-gpio.conf" >"$CONF"
}

run_avrdude() {
  "${AVRDUDE[@]}" -p "$PART" -C "$CONF" -c "$PROGRAMMER" -v "$@"
}
