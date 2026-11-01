import importlib.util
from pathlib import Path
import struct
import sys
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
                if args == ('w1@0x08', '12', 'r1'): return b'\x0a'
                if args == ('w1@0x08', '73', 'r13'):
                    armed = any(c[0] == 'w11@0x08' for c in self.calls)
                    return bytes((1, 1 if armed else 0, 0, 1)) + struct.pack('<HHI', 2, 3 if armed else 0, 100 if armed else 0) + b'\0'
                return b''
        transport = Fake(2)
        status = transport.change('arm', (2, 3, 100))
        self.assertEqual(status.identity, (2, 3, 100))
        self.assertEqual(transport.calls[3], ('w11@0x08', '72', '1', '1', '2', '0', '3', '0', '100', '0', '0', '0'))
        before = len(transport.calls)
        transport.change('arm', status.identity)
        self.assertEqual(len(transport.calls), before + 3)  # Read-only replay.


if __name__ == '__main__':
    unittest.main()
