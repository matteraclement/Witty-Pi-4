#!/bin/bash
# file: utilities.sh
#
# This script provides some useful utility functions
#

export LC_ALL=en_GB.UTF-8

if [ -z ${I2C_MC_ADDRESS+x} ]; then
  readonly I2C_MC_ADDRESS=0x08

  readonly I2C_BUS=1

  readonly I2C_ID=0
  readonly I2C_VOLTAGE_IN_I=1
  readonly I2C_VOLTAGE_IN_D=2
  readonly I2C_VOLTAGE_OUT_I=3
  readonly I2C_VOLTAGE_OUT_D=4
  readonly I2C_CURRENT_OUT_I=5
  readonly I2C_CURRENT_OUT_D=6
  readonly I2C_POWER_MODE=7
  readonly I2C_LV_SHUTDOWN=8
  readonly I2C_ALARM1_TRIGGERED=9
  readonly I2C_ALARM2_TRIGGERED=10
  readonly I2C_ACTION_REASON=11
  readonly I2C_FW_REVISION=12

  readonly I2C_CONF_ADDRESS=16
  readonly I2C_CONF_DEFAULT_ON=17
  readonly I2C_CONF_PULSE_INTERVAL=18
  readonly I2C_CONF_LOW_VOLTAGE=19
  readonly I2C_CONF_BLINK_LED=20
  readonly I2C_CONF_POWER_CUT_DELAY=21
  readonly I2C_CONF_RECOVERY_VOLTAGE=22
  readonly I2C_CONF_DUMMY_LOAD=23
  readonly I2C_CONF_ADJ_VIN=24
  readonly I2C_CONF_ADJ_VOUT=25
  readonly I2C_CONF_ADJ_IOUT=26

  readonly I2C_CONF_SECOND_ALARM1=27
  readonly I2C_CONF_MINUTE_ALARM1=28
  readonly I2C_CONF_HOUR_ALARM1=29
  readonly I2C_CONF_DAY_ALARM1=30
  readonly I2C_CONF_WEEKDAY_ALARM1=31

  readonly I2C_CONF_SECOND_ALARM2=32
  readonly I2C_CONF_MINUTE_ALARM2=33
  readonly I2C_CONF_HOUR_ALARM2=34
  readonly I2C_CONF_DAY_ALARM2=35
  readonly I2C_CONF_WEEKDAY_ALARM2=36

  readonly I2C_CONF_RTC_OFFSET=37
  readonly I2C_CONF_RTC_ENABLE_TC=38
  readonly I2C_CONF_FLAG_ALARM1=39
  readonly I2C_CONF_FLAG_ALARM2=40

  readonly I2C_CONF_IGNORE_POWER_MODE=41
  readonly I2C_CONF_IGNORE_LV_SHUTDOWN=42

  readonly I2C_CONF_BELOW_TEMP_ACTION=43
  readonly I2C_CONF_BELOW_TEMP_POINT=44
  readonly I2C_CONF_OVER_TEMP_ACTION=45
  readonly I2C_CONF_OVER_TEMP_POINT=46
  readonly I2C_CONF_DEFAULT_ON_DELAY=47

  readonly I2C_LM75B_TEMPERATURE=50
  readonly I2C_LM75B_CONF=51
  readonly I2C_LM75B_THYST=52
  readonly I2C_LM75B_TOS=53

  readonly I2C_RTC_CTRL1=54
  readonly I2C_RTC_CTRL2=55
  readonly I2C_RTC_OFFSET=56
  readonly I2C_RTC_RAM_BYTE=57
  readonly I2C_RTC_SECONDS=58
  readonly I2C_RTC_MINUTES=59
  readonly I2C_RTC_HOURS=60
  readonly I2C_RTC_DAYS=61
  readonly I2C_RTC_WEEKDAYS=62
  readonly I2C_RTC_MONTHS=63
  readonly I2C_RTC_YEARS=64
  readonly I2C_RTC_SECOND_ALARM=65
  readonly I2C_RTC_MINUTE_ALARM=66
  readonly I2C_RTC_HOUR_ALARM=67
  readonly I2C_RTC_DAY_ALARM=68
  readonly I2C_RTC_WEEKDAY_ALARM=69
  readonly I2C_RTC_TIMER_VALUE=70
  readonly I2C_RTC_TIMER_MODE=71
  readonly I2C_RTC_TRUST=74

  readonly HALT_PIN=4    # halt by GPIO-4 (BCM naming)
  readonly SYSUP_PIN=17  # output SYS_UP signal on GPIO-17 (BCM naming)
  readonly CHRG_PIN=5    # input to detect charging status
  readonly STDBY_PIN=6   # input to detect standby status

  readonly INTERNET_SERVER='http://google.com' # check network accessibility and get network time

  # reasons for startup/shutdown
  readonly REASON_ALARM1='0x01'
  readonly REASON_ALARM2='0x02'
  readonly REASON_CLICK='0x03'
  readonly REASON_LOW_VOLTAGE='0x04'
  readonly REASON_VOLTAGE_RESTORE='0x05'
  readonly REASON_OVER_TEMPERATURE='0x06'
  readonly REASON_BELOW_TEMPERATURE='0x07'
  readonly REASON_ALARM1_DELAYED='0x08'
  readonly REASON_USB_5V_CONNECTED='0x09'
  readonly REASON_POWER_CONNECTED='0x0a'
  readonly REASON_REBOOT='0x0b'
  readonly REASON_GUARANTEED_WAKE='0x0c'

  # config file
  if [ "$(lsb_release -si)" == "Ubuntu" ]; then
    # Ubuntu
    readonly BOOT_CONFIG_FILE="/boot/firmware/usercfg.txt"
  else
    # Raspberry Pi OS ("$(lsb_release -si)" == "Debian") and others
    readonly BOOT_CONFIG_FILE="/boot/config.txt"
  fi

  TIME_UNKNOWN=0

  SOFTWARE_VERSION='4.25'
fi


one_wire_confliction()
{
  if [[ $HALT_PIN -eq 4 ]]; then
    if grep -qe "^\s*dtoverlay=w1-gpio\s*$" ${BOOT_CONFIG_FILE}; then
      return 0
    fi
    if grep -qe "^\s*dtoverlay=w1-gpio-pullup\s*$" ${BOOT_CONFIG_FILE}; then
      return 0
    fi
  fi
  if grep -qe "^\s*dtoverlay=w1-gpio,gpiopin=$HALT_PIN\s*$" ${BOOT_CONFIG_FILE}; then
    return 0
  fi
  if grep -qe "^\s*dtoverlay=w1-gpio-pullup,gpiopin=$HALT_PIN\s*$" ${BOOT_CONFIG_FILE}; then
    return 0
  fi
  return 1
}

has_internet()
{
  curl -s --head --connect-timeout 3 "$INTERNET_SERVER" > /dev/null
  return $?
}

get_network_timestamp()
{
  local t=$(curl -sI --connect-timeout 3 "$INTERNET_SERVER" | grep -i "^Date:" | sed 's/Date: //Ig' | tr -d '\r')
  if [ -n "$t" ]; then
    date -d "$t" +%s 2>/dev/null || echo -1
  else
    echo -1
  fi
}

is_mc_connected()
{
  local result=$(i2cdetect -y ${I2C_BUS})
  if [[ $result == *"$(printf '%02x' $I2C_MC_ADDRESS)"* ]] ; then
    echo 1
  else
    echo 0
  fi
}

get_pi_model()
{
  IFS= read -r -d '' model </proc/device-tree/model
  echo $model;
}

get_os()
{
  echo $(hostnamectl | grep 'Operating System:' | sed 's/.*Operating System: //')
}

get_kernel()
{
  echo $(uname -sr)
}

get_arch()
{
  echo $(dpkg --print-architecture)
}

get_sys_time()
{
  echo $(date +'%Y-%m-%d %H:%M:%S %Z')
}

get_sys_timestamp()
{
  echo $(date +%s)
}

rtc_has_bad_time()
{
  rtc_is_trusted || return 1
  get_rtc_timestamp >/dev/null || return 1
  echo 0
}

# Revision 11 retains calendar trust across controller resets. Neither a
# plausible calendar nor a successful bus transfer is evidence of that trust.
rtc_is_trusted()
{
  local revision trust
  revision=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_FW_REVISION") || return 1
  if [[ $revision != 0x0b ]]; then
    echo 'Retained RTC trust requires reviewed firmware revision 11.' >&2
    return 1
  fi
  trust=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_RTC_TRUST") || return 1
  if [[ $trust != 0x01 ]]; then
    echo 'RTC calendar is untrusted; repair it from an independent time source.' >&2
    return 1
  fi
}

read_rtc_snapshot()
{
  rtc_is_trusted || return 1
  local snapshot
  snapshot=$(i2ctransfer -y "$I2C_BUS" "w1@$I2C_MC_ADDRESS" "$I2C_RTC_SECONDS" r7) || return 1
  if [[ ! $snapshot =~ ^[[:blank:]]*0x[0-9a-fA-F]{2}([[:blank:]]+0x[0-9a-fA-F]{2}){6}[[:blank:]]*$ ]]; then
    echo 'Incomplete or malformed RTC snapshot.' >&2
    return 1
  fi
  rtc_is_trusted || return 1
  echo "$snapshot"
}

# A revision-10 board retains an explicit UTC mode. Reading it never changes
# the calendar. Migration must first disarm and then rewrite/verify the RTC.
rtc_contract_mode()
{
  local revision mode
  revision=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_FW_REVISION") || return 1
  [[ $revision =~ ^0x[0-9a-fA-F]{2}$ ]] || return 1
  if (( revision < 10 )); then echo 0; return; fi
  (( revision == 10 || revision == 11 )) || return 1
  mode=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" 13) || return 1
  [[ $mode =~ ^0x0[01]$ ]] || return 1
  echo "$((mode))"
}

legacy_alarm_owner()
{
  local mode
  rtc_is_trusted || return 1
  mode=$(rtc_contract_mode) || return 1
  if [[ $mode != 0 ]]; then
    echo 'Legacy alarm editing is disabled in the managed UTC contract profile.' >&2
    return 1
  fi
}

get_rtc_timestamp()
{
  local snapshot mode
  snapshot=$(read_rtc_snapshot) || return 1
  mode=$(rtc_contract_mode) || return 1
  rtc_snapshot_timestamp "$snapshot" "$mode"
}

# Decode only complete, canonical calendars, including weekday and real dates.
rtc_snapshot_timestamp()
{
  local -a rtc
  read -r -a rtc <<< "$1"
  [[ ${#rtc[@]} == 7 ]] || return 1
  local value
  for value in "${rtc[@]}"; do
    [[ $value =~ ^0x[0-9a-fA-F]{2}$ ]] || return 1
  done
  if (( rtc[0] & 0x80 )); then
    echo 'RTC oscillator stopped; time is not reliable.' >&2
    return 1
  fi
  local index value
  for index in 0 1 2 3 5 6; do
    value=${rtc[index]}
    if (( (value & 0xF) > 9 || (value >> 4) > 9 )); then
      echo 'Invalid BCD in RTC calendar.' >&2
      return 1
    fi
  done
  if (( rtc[0] > 0x59 || rtc[1] > 0x59 || rtc[2] > 0x23 ||
        rtc[3] < 1 || rtc[3] > 0x31 || rtc[4] > 6 ||
        rtc[5] < 1 || rtc[5] > 0x12 )); then
    echo 'RTC calendar field out of range.' >&2
    return 1
  fi
  local sec=$(bcd2dec $((0x7F & rtc[0])))
  local min=$(bcd2dec "${rtc[1]}")
  local hour=$(bcd2dec "${rtc[2]}")
  local day=$(bcd2dec "${rtc[3]}")
  local month=$(bcd2dec "${rtc[5]}")
  local year=$(bcd2dec "${rtc[6]}")
  local timestamp canonical
  local -a zone=() expected
  [[ $2 == 1 ]] && zone=(-u)
  timestamp=$(date "${zone[@]}" --date="$((2000 + year))-$month-$day $hour:$min:$sec" +%s) || return 1
  canonical=$(date "${zone[@]}" -d "@$timestamp" '+0x%S 0x%M 0x%H 0x%d 0x0%w 0x%m 0x%y') || return 1
  read -r -a expected <<< "$canonical"
  for index in "${!rtc[@]}"; do
    (( rtc[index] == expected[index] )) || return 1
  done
  echo "$timestamp"
}

get_rtc_time()
{
  local rtc_ts
  if ! rtc_ts=$(get_rtc_timestamp); then
    echo 'N/A'
    return 1
  else
    date +'%Y-%m-%d %H:%M:%S %Z' -d "@$rtc_ts"
  fi
}

calc()
{
  awk "BEGIN { print $*}";
}

bcd2dec()
{
  local result=$(($1/16*10+($1&0xF)))
  echo $result
}

dec2bcd()
{
  local result=$((10#$1/10*16+(10#$1%10)))
  echo $result
}

dec2hex()
{
  printf "0x%02x" $1
}

hex2dec()
{
  printf "%d" $1
}

get_startup_time()
{
  legacy_alarm_owner || return 1
  local sec min hour date
  sec=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_SECOND_ALARM1") || return 1
  min=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_MINUTE_ALARM1") || return 1
  hour=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_HOUR_ALARM1") || return 1
  date=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_DAY_ALARM1") || return 1
  sec=$(bcd2dec "$sec"); min=$(bcd2dec "$min")
  hour=$(bcd2dec "$hour"); date=$(bcd2dec "$date")
  printf '%02d %02d:%02d:%02d\n' $date $hour $min $sec
}

set_startup_time()
{
  legacy_alarm_owner || return 1
  sec=$(dec2bcd $4)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_SECOND_ALARM1 $sec || return 1
  min=$(dec2bcd $3)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_MINUTE_ALARM1 $min || return 1
  hour=$(dec2bcd $2)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_HOUR_ALARM1 $hour || return 1
  date=$(dec2bcd $1)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_DAY_ALARM1 $date
}

clear_startup_time()
{
  legacy_alarm_owner || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_SECOND_ALARM1 0x00 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_MINUTE_ALARM1 0x00 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_HOUR_ALARM1 0x00 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_DAY_ALARM1 0x00
}

get_shutdown_time()
{
  legacy_alarm_owner || return 1
  local sec min hour date
  sec=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_SECOND_ALARM2") || return 1
  min=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_MINUTE_ALARM2") || return 1
  hour=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_HOUR_ALARM2") || return 1
  date=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_CONF_DAY_ALARM2") || return 1
  sec=$(bcd2dec "$sec"); min=$(bcd2dec "$min")
  hour=$(bcd2dec "$hour"); date=$(bcd2dec "$date")
  printf '%02d %02d:%02d:%02d\n' $date $hour $min $sec
}

set_shutdown_time()
{
  legacy_alarm_owner || return 1
  sec=$(dec2bcd $4)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_SECOND_ALARM2 $sec || return 1
  min=$(dec2bcd $3)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_MINUTE_ALARM2 $min || return 1
  hour=$(dec2bcd $2)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_HOUR_ALARM2 $hour || return 1
  date=$(dec2bcd $1)
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_DAY_ALARM2 $date
}

clear_shutdown_time()
{
  legacy_alarm_owner || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_SECOND_ALARM2 0x00 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_MINUTE_ALARM2 0x00 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_HOUR_ALARM2 0x00 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_DAY_ALARM2 0x00
}

net_to_system()
{
  local net_ts
  net_ts=$(get_network_timestamp) || return 1
  if [[ $net_ts =~ ^[0-9]+$ ]] && (( net_ts >= 946684800 && net_ts <= 4102444799 )); then
    log '  Applying network time to system...'
    sudo date -u -s "@$net_ts" >/dev/null || return 1
    log '  Done :-)'
  else
    log '  Can not get legit network time.'
    return 1
  fi
}

# Inspect contract state without reading the ordinary (possibly untrusted) RTC.
rtc_calendar_writable()
{
  local revision response
  revision=$(i2c_read "$I2C_BUS" "$I2C_MC_ADDRESS" "$I2C_FW_REVISION") || return 1
  [[ $revision == 0x0b ]] || return 1
  response=$(i2ctransfer -y "$I2C_BUS" "w1@$I2C_MC_ADDRESS" 73 r13) || return 1
  [[ $response =~ ^[[:blank:]]*0x[0-9a-fA-F]{2}([[:blank:]]+0x[0-9a-fA-F]{2}){12}[[:blank:]]*$ ]] || return 1
  local -a status
  read -r -a status <<< "$response"
  (( status[0] == 1 && status[1] <= 7 && status[2] == 0 &&
      status[3] <= 1 && status[12] <= 120 )) || return 1
  local boot=$((status[4] | status[5] << 8))
  local generation=$((status[6] | status[7] << 8))
  local due=$((status[8] | status[9] << 8 | status[10] << 16 | status[11] << 24))
  if (( status[1] != 0 && status[1] != 6 && (!boot || !generation || !due) )); then
    return 1
  fi
  if (( (status[1] == 3 && status[12] >= 60) ||
        (status[1] == 4 && (status[12] < 60 || status[12] >= 120)) ||
        (status[1] == 5 && status[12] != 120) ||
        (status[1] == 2 && status[12] >= 120) )); then
    return 1
  fi
  if (( status[1] == 1 || status[1] == 2 )); then
    echo 'Disarm the scheduled contract before changing the RTC calendar.' >&2
    return 1
  fi
}

system_to_rtc()
{
  log '  Writing independently accepted system time to RTC...'
  rtc_calendar_writable || return 1
  local sys_ts fields mode
  mode=$(rtc_contract_mode) || return 1
  sys_ts=$(get_sys_timestamp) || return 1
  [[ $sys_ts =~ ^[0-9]+$ ]] && (( sys_ts >= 946684800 && sys_ts <= 4102444799 )) || return 1
  local -a zone=() calendar
  [[ $mode == 1 ]] && zone=(-u)
  fields=$(date "${zone[@]}" -d "@$sys_ts" '+0x%S 0x%M 0x%H 0x%d 0x0%w 0x%m 0x%y') || return 1
  read -r -a calendar <<< "$fields"
  local accepted_ts
  accepted_ts=$(rtc_snapshot_timestamp "$fields" "$mode") || return 1
  (( accepted_ts == sys_ts )) || return 1
  if ! i2ctransfer -y "$I2C_BUS" "w8@$I2C_MC_ADDRESS" "$I2C_RTC_SECONDS" "${calendar[@]}"; then
    log '  Failed to write RTC calendar.' >&2
    return 1
  fi
  # Trust must be restored by firmware before a complete valid readback can be
  # accepted. Bound elapsed host time to five seconds, plus one RTC tick; compare
  # every field to the exact expected forward calendar, including rollovers.
  local snapshot rtc_ts end_ts
  if ! snapshot=$(read_rtc_snapshot) ||
      ! rtc_ts=$(rtc_snapshot_timestamp "$snapshot" "$mode") ||
      ! end_ts=$(get_sys_timestamp) || [[ ! $end_ts =~ ^[0-9]+$ ]] ||
      (( end_ts < sys_ts || end_ts - sys_ts > 5 ||
         rtc_ts < sys_ts || rtc_ts > end_ts + 1 )); then
    log '  Failed to verify RTC calendar write.' >&2
    return 1
  fi
  TIME_UNKNOWN=2
  log '  Done :-)'
}

rtc_to_system()
{
  log '  Writing RTC time to system...'
  local rtc_ts
  if ! rtc_ts=$(get_rtc_timestamp); then
    log '  RTC time is unavailable or invalid; system clock unchanged.' >&2
    return 1
  fi
  local ntp_state
  if ! ntp_state=$(timedatectl show --property=NTP --value) ||
      [[ $ntp_state != yes && $ntp_state != no ]]; then
    log '  Cannot determine NTP state; system clock unchanged.' >&2
    return 1
  fi
  if ! sudo timedatectl set-ntp 0 >/dev/null; then
    log '  Cannot disable NTP; system clock unchanged.' >&2
    return 1
  fi
  if ! sudo date -s "@$rtc_ts" >/dev/null; then
    if [[ $ntp_state == yes ]] && ! sudo timedatectl set-ntp 1 >/dev/null; then
      log '  Failed to restore NTP after clock-setting failure.' >&2
    fi
    log '  Failed to set system time from RTC.' >&2
    return 1
  fi
  TIME_UNKNOWN=0
  log '  Done :-)'
}

trim()
{
  local result=$(echo "$1" | sed -n '1h;1!H;${;g;s/^[ \t]*//g;s/[ \t]*$//g;p;}')
  echo $result
}

current_timestamp()
{
  get_rtc_timestamp
}

wittypi_home="`dirname \"$0\"`"
wittypi_home="`( cd \"$wittypi_home\" && pwd )`"
log2file()
{
  local datetime='[xxxx-xx-xx xx:xx:xx]'
  if [ $TIME_UNKNOWN -eq 0 ]; then
    datetime=$(date +'[%Y-%m-%d %H:%M:%S]')
  elif [ $TIME_UNKNOWN -eq 2 ]; then
    datetime=$(date +'<%Y-%m-%d %H:%M:%S>')
  fi
  local msg="$datetime $1"
  echo $msg >> $wittypi_home/wittyPi.log
}

log()
{
  if [ $# -gt 1 ] ; then
    echo $2 "$1"
  else
    echo "$1"
  fi
  log2file "$1"
}

i2c_read()
{
  local retry=0
  # Low-level calendar/alarm reads must not bypass the ordinary trust gate.
  if (( $2 == I2C_MC_ADDRESS && (($3 >= 27 && $3 <= 36) || ($3 >= 58 && $3 <= 71)) )); then
    rtc_is_trusted || return 1
  fi
  if [ $# -gt 3 ] ; then
    retry=$4
  fi
  local result
  if result=$(i2cget -y "$1" "$2" "$3") && [[ $result =~ ^0x[0-9a-fA-F]{2}$ ]]; then
    echo $result;
  else
    retry=$(( $retry + 1 ))
    if [ $retry -eq 4 ] ; then
      log "I2C read $1 $2 $3 failed (result=$result), and no more retry." >&2
      return 1
    else
      sleep 1
      log2file "I2C read $1 $2 $3 failed (result=$result), retrying $retry ..."
      i2c_read $1 $2 $3 $retry
    fi
  fi
}

i2c_write()
{
  if (( $2 == I2C_MC_ADDRESS )); then
    if (( $3 == I2C_RTC_CTRL1 || ($3 >= 58 && $3 <= 64) || $3 == I2C_RTC_TRUST )); then
      echo 'Use the verified full-calendar transaction; direct RTC mutation is disabled.' >&2
      return 1
    fi
    if (( ($3 >= 27 && $3 <= 36) || ($3 >= 65 && $3 <= 71) )); then
      legacy_alarm_owner || return 1
    fi
    if (( $3 == I2C_RTC_CTRL2 )); then
      local control
      control=$(i2c_read "$1" "$2" "$3") || return 1
      # Preserve alarm-flag acknowledgement, but not RTC reset/control changes.
      (( $4 == (control & 0xBF) )) || return 1
    fi
  fi
  local retry=0
  if [ $# -gt 4 ] ; then
    retry=$5
  fi
  i2cset -y "$1" "$2" "$3" "$4" || return 1
  local result
  result=$(i2c_read "$1" "$2" "$3") || return 1
  if [ "$result" != $(dec2hex "$4") ] ; then
    retry=$(( $retry + 1 ))
    if [ $retry -eq 4 ] ; then
      log "I2C write $1 $2 $3 $4 failed (result=$result), and no more retry."
      return 1
    else
      sleep 1
      log2file "I2C write $1 $2 $3 $4 failed (result=$result), retrying $retry ..."
      i2c_write $1 $2 $3 $4 $retry
    fi
  fi
}

get_temperature()
{
  local data=$(i2cget -y $I2C_BUS $I2C_MC_ADDRESS $I2C_LM75B_TEMPERATURE w)

  #if [[ $data =~ ^0x[0-9a-fA-F]{4}$ && $data != 0xffff ]]; then
  if [[ $data =~ ^0x[0-9a-fA-F]{4}$ ]]; then
    data=$(( ((($data&0xFF)<<8)|(($data&0xFF00)>>8))>>5 ))
    if [[ $data -ge 0x400 ]] ; then
      data=$(( ($data&0x3FF)-1024 ))
    fi
    local c=$(calc $data*0.125)
    echo -n "$c$(echo $'\xc2\xb0'C)"
    if hash awk 2>/dev/null; then
      local f=$(awk "BEGIN { print $c*1.8+32 }")
      echo " / $f$(echo $'\xc2\xb0'F)"
    else
      echo ''
    fi
  else
    sleep 0.1
    get_temperature
  fi
}

clear_alarm_flags()
{
  local ctrl2=0x0
  if [ -z "$1" ]; then
    ctrl2=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_RTC_CTRL2) || return 1
  else
    ctrl2=$1
  fi
  ctrl2=$(($ctrl2&0xBF))
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_RTC_CTRL2 $ctrl2 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_FLAG_ALARM1 0 || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_FLAG_ALARM2 0
}

do_shutdown()
{
  local halt_pin=$1
  local has_mc=$2

  # restore halt pin
  gpio -g mode $halt_pin in
  gpio -g mode $halt_pin up

  # clear alarm flags
  if [ "$has_mc" == "1" ] ; then
    clear_alarm_flags
  fi

  log 'Halting all processes and then shutdown Raspberry Pi...'

  # halt everything and shutdown
  if [ ! -f /boot/wittypi.lock ]; then
    shutdown -h now
  else
    rm /boot/wittypi.lock
  fi
}

schedule_script_interrupted()
{
  local startup_time=$(get_startup_time)
  local shutdown_time=$(get_shutdown_time)
  if [ "$startup_time" != '00 00:00:00' ] && [ "$shutdown_time" != '00 00:00:00' ] ; then
    local st_timestamp=$(date --date="$(date +%Y-%m-)$startup_time" +%s)
    local sd_timestamp=$(date --date="$(date +%Y-%m-)$shutdown_time" +%s)
    local cur_timestamp=$(date +%s)
    if [ $st_timestamp -gt $cur_timestamp ] && [ $sd_timestamp -lt $cur_timestamp ] ; then
      return 0
    fi
  fi
  return 1
}

get_power_mode()
{
  local mode=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_POWER_MODE)
  echo $(($mode))
}

get_input_voltage()
{
  local i=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_VOLTAGE_IN_I)
  local d=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_VOLTAGE_IN_D)
  calc $(($i))+$(($d))/100
}

get_output_voltage()
{
  local i=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_VOLTAGE_OUT_I)
  local d=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_VOLTAGE_OUT_D)
  calc $(($i))+$(($d))/100
}

get_output_current()
{
  local i=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CURRENT_OUT_I)
  local d=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CURRENT_OUT_D)
  calc $(($i))+$(($d))/100
}

get_low_voltage_threshold()
{
  local lowVolt=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_LOW_VOLTAGE)
  if [ $(($lowVolt)) == 255 ]; then
    lowVolt='disabled'
  else
    lowVolt=$(calc $(($lowVolt))/10)
    lowVolt+='V'
  fi
  echo $lowVolt;
}

get_recovery_voltage_threshold()
{
  local recVolt=$(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_RECOVERY_VOLTAGE)
  if [ $(($recVolt)) == 255 ]; then
    recVolt='disabled'
  else
    recVolt=$(calc $(($recVolt))/10)
    recVolt+='V'
  fi
  echo $recVolt;
}

set_low_voltage_threshold()
{
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_LOW_VOLTAGE $1
}

set_recovery_voltage_threshold()
{
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_RECOVERY_VOLTAGE $1
}

clear_low_voltage_threshold()
{
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_LOW_VOLTAGE 0xFF
}

clear_recovery_voltage_threshold()
{
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_RECOVERY_VOLTAGE 0xFF
}

get_over_temperature_action()
{
  hex2dec $(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_OVER_TEMP_ACTION)
}

get_over_temperature_point()
{
  local t=$(hex2dec $(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_LM75B_TOS))
  if [ $(($t>127)) == '1' ]; then
    t=$(($t-256))
  fi
  printf "%d" $t
}

get_below_temperature_action()
{
  hex2dec $(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_BELOW_TEMP_ACTION)
}

get_below_temperature_point()
{
  local t=$(hex2dec $(i2c_read ${I2C_BUS} $I2C_MC_ADDRESS $I2C_LM75B_THYST))
  if [ $(($t>127)) == '1' ]; then
    t=$(($t-256))
  fi
  printf "%d" $t
}

over_temperature_action()
{
  if [ $# -eq 0 ]; then
    over_temperature_action $(get_over_temperature_action) $(get_over_temperature_point)
  else
    local action='None'
    if [ "$1" == '1' ]; then
      action='Shutdown'
    elif [ "$1" == '2' ]; then
      action='Startup'
    fi
    if [ "$action" != 'None' ]; then
      echo -n "T>$2$(echo $'\xc2\xb0'C) $(echo -e '\u2794') $action"
    fi
  fi
}

below_temperature_action()
{
  if [ $# -eq 0 ]; then
    below_temperature_action $(get_below_temperature_action) $(get_below_temperature_point)
  else
    local action='None'
    if [ "$1" == '1' ]; then
      action='Shutdown'
    elif [ "$1" == '2' ]; then
      action='Startup'
    fi
    if [ "$action" != 'None' ]; then
      echo -n "T<$2$(echo $'\xc2\xb0'C) $(echo -e '\u2794') $action"
    fi
  fi
}

# Registers 52/53 map to two-byte LM75B limits, and the firmware forwards only
# complete writes: send the point as an i2cset word (point byte, then a zero
# fraction byte) and verify the point byte read back.
lm75b_limit_write()
{
  local result
  i2cset -y "${I2C_BUS}" "$I2C_MC_ADDRESS" "$1" "$2" w || return 1
  result=$(i2c_read "${I2C_BUS}" "$I2C_MC_ADDRESS" "$1") || return 1
  if [ "$result" != "$(dec2hex "$2")" ]; then
    log "LM75B limit write $1 $2 failed (result=$result)."
    return 1
  fi
}

# Disarm, retarget, then arm: no intermediate state pairs an enabled action with
# a point that was not set for it. A failed write leaves the action disarmed.
# The firmware compares against the configured point, not the LM75B mirror, so
# the mirror write's result does not decide whether the action is armed.
set_over_temperature_action()
{
  local t=$2
  if [ $(($2<0)) == '1' ]; then
    t=$(($2+256))
  fi
  clear_over_temperature_action || return 1
  lm75b_limit_write $I2C_LM75B_TOS $t
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_OVER_TEMP_POINT $t || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_OVER_TEMP_ACTION $1
}

set_below_temperature_action()
{
  local t=$2
  if [ $(($2<0)) == '1' ]; then
    t=$(($2+256))
  fi
  clear_below_temperature_action || return 1
  lm75b_limit_write $I2C_LM75B_THYST $t
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_BELOW_TEMP_POINT $t || return 1
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_BELOW_TEMP_ACTION $1
}

clear_over_temperature_action()
{
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_OVER_TEMP_ACTION 0x00
}

clear_below_temperature_action()
{
  i2c_write ${I2C_BUS} $I2C_MC_ADDRESS $I2C_CONF_BELOW_TEMP_ACTION 0x00
}

check_sys_and_rtc_time()
{
  local rtc_ts
  if ! rtc_ts=$(get_rtc_timestamp); then
    echo '[Warning] RTC time is unavailable or invalid; synchronize time before scheduling.'
    return 1
  fi
  local sys_ts=$(get_sys_timestamp)
  local delta=$((rtc_ts-sys_ts))
  if [ "${delta#-}" -gt 10 ]; then
    local rtc_t=$(date +'%Y-%m-%d %H:%M:%S %Z' -d @$rtc_ts)
    local sys_t=$(date +'%Y-%m-%d %H:%M:%S %Z' -d @$sys_ts)
    echo "[Warning] System and RTC time seems not synchronized, difference is ${delta#-}s."
    echo "System time is \"$sys_t\", while RTC time is \"$rtc_t\"."
    echo 'Please synchronize the time first.'
  fi
}
