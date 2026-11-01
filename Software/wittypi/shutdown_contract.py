#!/usr/bin/python3
"""Revision-10 scheduled contract transport and late filesystem completion.

Nothing is armed on import or by a status read. The late path reports visible
mount safety, not kernel halt, recording success, or measured removal of VOUT.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import struct
import subprocess
import time


PHASES = ('idle', 'armed', 'active', 'normal', 'late', 'expired', 'unknown', 'cancelled')
VOLATILE_FILESYSTEMS = frozenset(('tmpfs', 'devtmpfs', 'proc', 'sysfs', 'devpts',
    'cgroup', 'cgroup2', 'securityfs', 'debugfs', 'tracefs', 'pstore', 'configfs',
    'mqueue', 'hugetlbfs', 'ramfs', 'bpf', 'nsfs', 'fusectl', 'autofs', 'binfmt_misc'))


@dataclass(frozen=True)
class Status:
    phase: str
    utc_profile: bool
    boot: int
    generation: int
    due_utc: int
    elapsed_seconds: int

    @property
    def identity(self) -> tuple[int, int, int]:
        return self.boot, self.generation, self.due_utc

    def document(self) -> dict:
        return {**asdict(self), 'contract': 'scheduled-shutdown-v1',
                'normal_seconds': 60, 'emergency_seconds': 120,
                'retention': 'eeprom-journal',
                'completion_evidence': ('host_readonly_mounts_report'
                    if self.phase in ('normal', 'late') else 'none'),
                'cut_evidence': ('commanded'
                    if self.phase in ('normal', 'late', 'expired') else 'unconfirmed')}


def decode(data: bytes) -> Status:
    if len(data) != 13 or data[0] != 1 or data[1] >= len(PHASES) or data[2] or data[3] > 1:
        raise ValueError('Invalid scheduled-contract response')
    boot, generation, due = struct.unpack_from('<HHI', data, 4)
    phase, elapsed = PHASES[data[1]], data[12]
    if elapsed > 120 or (phase not in ('idle', 'unknown') and (not boot or not generation or not due)):
        raise ValueError('Invalid scheduled-contract identity or age')
    if ((phase == 'normal' and elapsed >= 60) or (phase == 'late' and not 60 <= elapsed < 120)
            or (phase == 'expired' and elapsed != 120) or (phase == 'active' and elapsed >= 120)):
        raise ValueError('Contradictory scheduled-contract outcome')
    return Status(phase, bool(data[3]), boot, generation, due, elapsed)


def readonly_mounts(mountinfo: str, swaps: str) -> bool:
    lines = swaps.splitlines()
    if not lines or not lines[0].startswith('Filename') or any(line.strip() for line in lines[1:]):
        return False
    root = False
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(' - ')
        fields, filesystem = before.split(), after.split()
        if not separator or len(fields) < 6 or len(filesystem) < 3:
            return False
        root = root or fields[4] == '/'
        modes = set(fields[5].split(',')) & {'ro', 'rw'}
        if len(modes) != 1:
            return False
        if 'rw' in modes and filesystem[0] not in VOLATILE_FILESYSTEMS:
            return False
    return root


def filesystem_ready() -> bool:
    return readonly_mounts(Path('/proc/self/mountinfo').read_text(), Path('/proc/swaps').read_text())


class Transport:
    def __init__(self, deadline: float):
        self.deadline = deadline

    def transfer(self, *args: str) -> bytes:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Scheduled-contract I/O budget exhausted')
        result = subprocess.run(['/usr/sbin/i2ctransfer', '-y', '1', *args],
            capture_output=True, text=True, timeout=remaining, check=True)
        tokens = result.stdout.split()
        if any(re.fullmatch(r'0x[0-9a-fA-F]{2}', token) is None for token in tokens):
            raise ValueError('Invalid I2C response')
        return bytes(int(token, 16) for token in tokens)

    def read(self) -> Status:
        product = self.transfer('w1@0x08', '0', 'r1')
        revision = self.transfer('w1@0x08', '12', 'r1')
        if product not in (b'\x26', b'\x36', b'\x37') or revision != b'\x0a':
            raise ValueError('Scheduled contract requires a reviewed revision-10 WP4 product')
        return decode(self.transfer('w1@0x08', '73', 'r13'))

    def write(self, action: int, identity: tuple[int, int, int]) -> None:
        boot, generation, due = identity
        payload = bytes((72, 1, action)) + struct.pack('<HHI', boot, generation, due)
        if self.transfer('w11@0x08', *(str(value) for value in payload)):
            raise ValueError('Unexpected write response')

    def change(self, action: str, identity: tuple[int, int, int]) -> Status:
        before = self.read()
        if action == 'arm' and before.identity == identity and before.phase in ('armed', 'active'):
            return before
        if action != 'arm' and before.identity != identity:
            raise ValueError('Controller identity changed')
        if action == 'cancel' and before.phase == 'cancelled':
            return before
        if (action == 'ack' and before.phase == 'idle') or (action == 'enable-utc' and before.phase == 'idle' and before.utc_profile):
            return before
        self.write({'arm': 1, 'cancel': 2, 'ack': 4, 'enable-utc': 5}[action], identity)
        after = self.read()
        expected = {'arm': ('armed', 'active'), 'cancel': ('cancelled',),
                    'ack': ('idle',), 'enable-utc': ('idle',)}[action]
        accepted_identities = (identity, (identity[0] + 1, *identity[1:])) if action == 'ack' else (identity,)
        if after.phase not in expected or after.identity not in accepted_identities:
            raise RuntimeError('Controller did not accept the requested transition')
        if action == 'enable-utc' and not after.utc_profile:
            raise RuntimeError('Controller UTC profile not enabled')
        return after


def late_completion(transport: Transport) -> None:
    if not filesystem_ready():
        raise RuntimeError('Writable persistent mounts or active swap prevent completion report')
    status = transport.read()
    if status.phase != 'active':
        return
    if not filesystem_ready():
        raise RuntimeError('Filesystem state changed during completion preparation')
    # Do not write host storage, invoke hooks or wait for readback after this
    # command: the controller may already have removed host power.
    transport.write(3, status.identity)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'arm', 'cancel', 'ack', 'enable-utc', 'late-completion'))
    parser.add_argument('identity', nargs='?', help='decimal boot:generation:due-utc')
    args = parser.parse_args()
    transport = Transport(time.monotonic() + 2)
    if args.action == 'late-completion':
        late_completion(transport)
        return
    if args.action == 'status':
        result = transport.read()
    else:
        if not args.identity or re.fullmatch(r'[0-9]+:[0-9]+:[0-9]+', args.identity) is None:
            parser.error('A complete decimal identity is required')
        boot, generation, due = (int(part) for part in args.identity.split(':'))
        if not (0 <= boot <= 65535 and 0 <= generation <= 65535 and 0 <= due <= 4102444799):
            parser.error('Identity is outside the firmware representation')
        result = transport.change(args.action, (boot, generation, due))
    print(json.dumps(result.document(), sort_keys=True))


if __name__ == '__main__':
    main()
