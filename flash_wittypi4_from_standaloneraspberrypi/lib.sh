# shellcheck shell=bash
# Shared by check.sh and flash.sh: avrdude over the Raspberry Pi GPIO programmer.

FLASH_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PART=attiny841
PROGRAMMER=RasPi

die() {
  echo "error: $*" >&2
  exit 1
}

# Newest wp4-* bundle in ../release (version sort), for callers given no release-dir.
newest_bundle() {
  local bundle
  bundle=$(find "$FLASH_DIR/../release" -mindepth 1 -maxdepth 1 -type d -name 'wp4-*' 2>/dev/null | sort -V | tail -n 1)
  [ -n "$bundle" ] || die "no wp4-* bundle in $FLASH_DIR/../release (pass a release-dir)"
  echo "$bundle"
}

# Verify a bundle offline, then set release, hex, product_id, revision, software and name for one variant.
load_bundle() {
  local variant=$2 artifact
  local python=${PYTHON:-python3} tool=${RELEASE_TOOL:-$FLASH_DIR/../tools/release.py}
  [ -f "$tool" ] || die "release tool not found: $tool (copy tools/ next to this folder)"
  [ -d "$1" ] || die "not a directory: $1"
  release=$(cd "$1" && pwd)

  "$python" "$tool" verify "$release" || die "bundle verification failed; avrdude was not run"

  IFS=$'\t' read -r artifact product_id revision software name < <(
    "$python" - "$release/release-manifest.json" "$variant" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
for entry in manifest["variants"]:
    if entry["name"] == sys.argv[2]:
        print("\t".join([
            entry["artifact"],
            entry["product_id"],
            str(manifest["compatibility"]["nominal_revision"]),
            manifest["software_version"],
            manifest["release_name"],
        ]))
        break
else:
    sys.exit("release: manifest has no variant " + sys.argv[2])
PY
  ) || die "cannot read variant $variant from $release/release-manifest.json"
  hex=$release/$artifact
  [ -f "$hex" ] || die "missing $hex"
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
