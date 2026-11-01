import importlib.util
from datetime import datetime, timezone
import os
from pathlib import Path
import struct
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('wp4_contract_host',
    ROOT / 'Software/wittypi/shutdown_contract.py')
host = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = host
SPEC.loader.exec_module(host)


class ContractHost(unittest.TestCase):
    def test_golden_wire_and_rejected_contradictory_results(self):
        raw = bytes.fromhex('01 04 00 01 34 12 78 56 00 00 00 67 3c')
        status = host.decode(raw)
        self.assertEqual(status.identity, (0x1234, 0x5678, 0x67000000))
        self.assertEqual(status.phase, 'late')
        self.assertEqual(status.document()['completion_evidence'], 'host_readonly_mounts_report')
        for index, value in ((0, 2), (1, 9), (2, 1), (3, 2), (12, 59), (12, 120)):
            invalid = bytearray(raw)
            invalid[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                host.decode(invalid)
        for partial in (raw[:-1], raw + b'\0'):
            with self.assertRaises(ValueError):
                host.decode(partial)

    def test_readonly_report_rejects_swap_unknown_mounts_and_malformed_records(self):
        root = '1 0 8:1 / / ro,relatime - ext4 /dev/root ro\n'
        temporary = '2 1 0:2 / /run rw,nosuid - tmpfs tmpfs rw\n'
        swaps = 'Filename Type Size Used Priority\n'
        self.assertTrue(host.readonly_mounts(root + temporary, swaps))
        for mounts, swap in ((root.replace('ro,', 'rw,'), swaps),
                (root + temporary.replace('tmpfs', 'overlay'), swaps),
                (root + 'malformed\n', swaps), (temporary, swaps),
                (root.replace('ro,relatime', 'relatime'), swaps),
                (root, swaps + '/swapfile file 1024 0 -2\n'), (root, '')):
            with self.subTest(mounts=mounts, swap=swap):
                self.assertFalse(host.readonly_mounts(mounts, swap))

    def test_late_helper_requires_fresh_filesystem_report_and_exact_active_identity(self):
        class Fake:
            writes = []
            def read(self):
                return host.Status('active', True, 4, 8, 1793534400, 61)
            def write(self, action, identity):
                self.writes.append((action, identity))
        fake = Fake()
        with patch.object(host, 'filesystem_ready', side_effect=(True, False)):
            with self.assertRaises(RuntimeError):
                host.late_completion(fake)
        self.assertEqual(fake.writes, [])
        with patch.object(host, 'filesystem_ready', return_value=True):
            host.late_completion(fake)
        self.assertEqual(fake.writes, [(3, (4, 8, 1793534400))])

    def test_transport_reads_before_mutation_and_verifies_complete_identity(self):
        class Fake(host.Transport):
            calls = []
            def transfer(self, *args):
                self.calls.append(args)
                if args == ('w1@0x08', '0', 'r1'): return b'\x26'
                if args == ('w1@0x08', '12', 'r1'): return b'\x0b'
                if args == ('w1@0x08', '74', 'r1'): return b'\x01'
                if args == ('w1@0x08', '73', 'r13'):
                    armed = any(c[0] == 'w11@0x08' for c in self.calls)
                    return bytes((1, 1 if armed else 0, 0, 1)) + struct.pack('<HHI', 2, 3 if armed else 0, 100 if armed else 0) + b'\0'
                return b''
        transport = Fake(2)
        status = transport.change('arm', (2, 3, 100))
        self.assertEqual(status.identity, (2, 3, 100))
        self.assertEqual(transport.calls[5], ('w11@0x08', '72', '1', '1', '2', '0', '3', '0', '100', '0', '0', '0'))
        before = len(transport.calls)
        transport.change('arm', status.identity)
        self.assertEqual(len(transport.calls), before + 5)  # Read-only trusted replay.

    def test_untrusted_arm_and_replay_never_mutate_but_status_remains_available(self):
        class Fake(host.Transport):
            def __init__(self, revision, trust):
                self.revision, self.trust, self.calls = revision, trust, []
            def transfer(self, *args):
                self.calls.append(args)
                if args == ('w1@0x08', '0', 'r1'): return b'\x26'
                if args == ('w1@0x08', '12', 'r1'): return self.revision
                if args == ('w1@0x08', '74', 'r1'): return self.trust
                if args == ('w1@0x08', '73', 'r13'):
                    return bytes((1, 1, 0, 1)) + struct.pack('<HHI', 2, 3, 100) + b'\0'
                raise AssertionError(args)
        for revision, trust in ((b'\x0b', b'\0'), (b'\x0b', b'\xff'),
                (b'\x0b', b''), (b'\x0b', b'\x01\x01'), (b'\x0a', b'\x01')):
            with self.subTest(revision=revision, trust=trust):
                transport = Fake(revision, trust)
                self.assertEqual(transport.read().phase, 'armed')
                for identity in ((2, 3, 100), (2, 4, 101)):
                    with self.assertRaises(ValueError):
                        transport.change('arm', identity)
                with self.assertRaises(ValueError):
                    transport.write(1, (2, 4, 101))
                self.assertFalse(any(call[0] == 'w11@0x08' for call in transport.calls))

    def test_disarmed_utc_enable_does_not_require_calendar_trust(self):
        class Fake(host.Transport):
            def __init__(self):
                self.calls = []
            def transfer(self, *args):
                self.calls.append(args)
                if args == ('w1@0x08', '0', 'r1'): return b'\x26'
                if args == ('w1@0x08', '12', 'r1'): return b'\x0b'
                if args == ('w1@0x08', '73', 'r13'):
                    enabled = any(call[0] == 'w11@0x08' for call in self.calls)
                    return bytes((1, 0, 0, int(enabled))) + struct.pack('<HHI', 2, 0, 0) + b'\0'
                if args[0] == 'w11@0x08': return b''
                raise AssertionError(args)
        transport = Fake()
        self.assertTrue(transport.change('enable-utc', (2, 0, 0)).utc_profile)
        self.assertNotIn(('w1@0x08', '74', 'r1'), transport.calls)


class VendorCalendar(unittest.TestCase):
    """Exercise the actual sourced vendor functions with fake external I2C."""

    START = int(datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    FIXTURE = r'''
lsb_release() { echo Debian; }
source "$1"
log() { printf '%s\n' "$1" >> "$TRACE"; }
log2file() { :; }
sleep() { :; }
get_sys_timestamp() {
  if [[ -f "$WRITTEN" ]]; then echo "$END"; else echo "$START"; fi
}
i2cget() {
  printf 'get %s\n' "$4" >> "$TRACE"
  case "$4" in
    12) echo "$REVISION";;
    13) echo "$MODE";;
    74) cat "$TRUST_FILE";;
    55) if [[ -f "$CONTROL_FILE" ]]; then cat "$CONTROL_FILE"; else echo 0x40; fi;;
    *) if [[ -f "$REGISTER_PREFIX$4" ]]; then cat "$REGISTER_PREFIX$4"; else echo 0x00; fi;;
  esac
}
i2cset() {
  printf 'set %s %s\n' "$4" "$5" >> "$TRACE"
  printf '0x%02x\n' "$5" > "$REGISTER_PREFIX$4"
  if [[ $4 == 55 ]]; then printf '0x%02x\n' "$5" > "$CONTROL_FILE"; fi
}
i2ctransfer() {
  printf 'transfer %s %s\n' "$3" "$4" >> "$TRACE"
  if [[ $3 == w8@* ]]; then
    printf 'calendar %s\n' "$*" >> "$TRACE"
    [[ $WRITE_FAILURE == 0 ]] || return 1
    printf '%s\n' "$POST_TRUST" > "$TRUST_FILE"
    touch "$WRITTEN"
  elif [[ $4 == 73 ]]; then
    echo "$STATUS"
  elif [[ $4 == 58 ]]; then
    if [[ $DROP_TRUST == 1 ]]; then echo 0x00 > "$TRUST_FILE"; fi
    [[ $READ_FAILURE == 0 ]] || return 1
    echo "$SNAPSHOT"
  else
    return 1
  fi
}
'''

    def vendor(self, action, boot=False, **settings):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'trace'
            trust = Path(directory) / 'trust'
            trust.write_text(settings.pop('TRUST', '0x01'))
            status = bytes((1, 0, 0, 1)) + struct.pack('<HHI', 2, 0, 0) + b'\0'
            env = {**os.environ, 'TZ': 'UTC', 'TRACE': str(trace),
                'TRUST_FILE': str(trust), 'WRITTEN': str(Path(directory) / 'written'),
                'CONTROL_FILE': str(Path(directory) / 'control'),
                'REGISTER_PREFIX': str(Path(directory) / 'register-'),
                'REVISION': '0x0b', 'MODE': '0x01', 'POST_TRUST': '0x01',
                'START': str(self.START), 'END': str(self.START),
                'SNAPSHOT': '0x00 0x00 0x00 0x01 0x05 0x01 0x27',
                'STATUS': ' '.join(f'0x{value:02x}' for value in status),
                'WRITE_FAILURE': '0', 'READ_FAILURE': '0', 'DROP_TRUST': '0',
                **{key: str(value) for key, value in settings.items()}}
            utility = ROOT / 'Software/wittypi/utilities.sh'
            if boot:
                gpio = Path(directory) / 'gpio'
                gpio.write_text('#!/bin/bash\nexit 0\n')
                gpio.chmod(0o755)
                env['PATH'] = directory + os.pathsep + env['PATH']
                utility_copy = Path(directory) / 'utilities.sh'
                utility_copy.write_text(utility.read_text() +
                    self.FIXTURE.replace('source "$1"', '') + r'''
one_wire_confliction() { return 1; }
is_mc_connected() { echo 1; }
get_os() { echo test; }
get_kernel() { echo test; }
get_arch() { echo test; }
get_pi_model() { echo test; }
gpio() { echo 1; }
# End the real daemon at its GPIO-settling delay, after boot clock and
# protection initialization but before any user hooks or event wait.
sleep() { exit 0; }
''')
                utility = Path(directory) / 'daemon.sh'
                utility.write_text((ROOT / 'Software/wittypi/daemon.sh').read_text())
                script = 'lsb_release() { echo Debian; }\nsource "$1"'
            else:
                script = self.FIXTURE + '\n' + action
            result = subprocess.run(['bash', '-c', script,
                'vendor-calendar-test', str(utility)],
                env=env, text=True, capture_output=True, check=False)
            return result, trace.read_text() if trace.exists() else ''

    def test_untrusted_ordinary_time_alarm_and_raw_access_fail_closed(self):
        actions = ('get_rtc_timestamp', 'rtc_to_system', 'current_timestamp',
            'get_startup_time', 'get_shutdown_time', 'set_startup_time 01 00 00 01',
            'set_shutdown_time 01 00 00 01', 'clear_startup_time', 'clear_shutdown_time',
            'i2c_read 1 0x08 58', 'i2c_read 1 0x08 27',
            'i2c_write 1 0x08 27 1', 'i2c_write 1 0x08 65 1')
        for trust in ('0x00', '0xff', '', 'garbage'):
            for action in actions:
                with self.subTest(trust=trust, action=action):
                    result, trace = self.vendor(action, TRUST=trust)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('transfer ', trace)
                    self.assertNotIn('set ', trace)

    def test_trusted_ordinary_time_and_legacy_alarms_still_work(self):
        result, trace = self.vendor('get_rtc_timestamp')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.START + 1))
        for kind in ('startup', 'shutdown'):
            with self.subTest(kind=kind):
                result, trace = self.vendor(
                    f'set_{kind}_time 01 02 03 04 && get_{kind}_time', MODE='0x00')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '01 02:03:04')
                self.assertEqual(sum(line.startswith('set ') for line in trace.splitlines()), 4)
                result, trace = self.vendor(f'set_{kind}_time 01 02 03 04')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('set ', trace)

    def test_repair_accepts_only_bounded_elapsed_forward_calendar(self):
        result, trace = self.vendor('system_to_rtc', TRUST='0x00',
            END=self.START + 2, SNAPSHOT='0x02 0x00 0x00 0x01 0x05 0x01 0x27')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Done', trace)

    def test_repair_does_not_read_untrusted_calendar_and_accepts_year_rollover(self):
        result, trace = self.vendor('system_to_rtc', TRUST='0x00')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(trace.index('transfer w8@0x08 58'), trace.index('get 74'))
        self.assertLess(trace.index('get 74'), trace.index('transfer w1@0x08 58'))
        self.assertIn('Done', trace)
        self.assertNotIn('set ', trace)
        self.assertIn('calendar -y 1 w8@0x08 58 0x59 0x59 0x23 0x31 0x04 0x12 0x26', trace)

    def test_repair_rejects_bad_readback_or_missing_firmware_trust(self):
        failures = ({'POST_TRUST': '0x00'}, {'POST_TRUST': '0xff'},
            {'READ_FAILURE': '1'}, {'WRITE_FAILURE': '1'}, {'DROP_TRUST': '1'},
            {'SNAPSHOT': '0x00 0x00 0x00 0x01 0x04 0x01 0x27'},
            {'SNAPSHOT': '0x00 0x00 0x00 0x30 0x02 0x02 0x27'},
            {'SNAPSHOT': '0x80 0x00 0x00 0x01 0x05 0x01 0x27'},
            {'SNAPSHOT': '0xff 0xff 0xff 0xff 0xff 0xff 0xff'},
            {'SNAPSHOT': '0x00 0x00 0x00 0x01 0x05 0x01'},
            {'SNAPSHOT': '0x02 0x00 0x00 0x01 0x05 0x01 0x27'},
            {'END': self.START - 1}, {'END': self.START + 6},
            {'START': '0'}, {'REVISION': '0x0a'})
        for settings in failures:
            with self.subTest(settings=settings):
                result, trace = self.vendor('system_to_rtc', TRUST='0x00', **settings)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('Done', trace)

    def test_locked_or_malformed_contract_rejects_repair_before_mutation(self):
        statuses = []
        for phase in (1, 2):
            raw = bytes((1, phase, 0, 1)) + struct.pack('<HHI', 2, 3, 100) + b'\0'
            statuses.append(' '.join(f'0x{value:02x}' for value in raw))
        statuses.extend(('', '0x01', 'garbage'))
        for status in statuses:
            with self.subTest(status=status):
                result, trace = self.vendor('system_to_rtc', STATUS=status)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('transfer w8', trace)
                self.assertNotIn('set ', trace)
                self.assertNotIn('get 74', trace)

    def test_control_calendar_loopholes_blocked_but_protection_and_flag_clear_work(self):
        for register in (54, 58, 59, 60, 61, 62, 63, 64, 74):
            result, trace = self.vendor(f'i2c_write 1 0x08 {register} 0')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('set ', trace)
        result, trace = self.vendor('i2c_write 1 0x08 55 0x10')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('set ', trace)
        result, trace = self.vendor('i2c_write 1 0x08 19 0', TRUST='0x00')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('set 19 0', trace)
        result, trace = self.vendor('clear_alarm_flags', TRUST='0x00')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('set 55 0', trace)
        self.assertIn('set 39 0', trace)
        self.assertIn('set 40 0', trace)

    def test_boot_never_clears_control_or_repairs_from_an_unaccepted_system_clock(self):
        result, trace = self.vendor('', boot=True, TRUST='0x00')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('skipping clock synchronization', trace)
        self.assertNotIn('transfer w8', trace)
        self.assertNotIn('transfer w1@0x08 58', trace)
        self.assertNotIn('set 54 ', trace)
        self.assertIn('set 52 ', trace)  # Non-time temperature protection remains.
        self.assertIn('set 53 ', trace)


if __name__ == '__main__':
    unittest.main()
