#!/bin/bash
# Read-only link test: reads the MCU signature and fuses, writes nothing.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

[ "$#" -eq 0 ] || die "usage: check.sh"
select_avrdude
build_conf
run_avrdude
