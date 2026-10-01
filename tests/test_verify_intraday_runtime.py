"""Regression tests for the VM runtime verifier."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.verify_intraday_runtime import parse_environ


class ParseEnvironTests(unittest.TestCase):
    def test_bytes_are_split_without_decoding_values(self):
        payload = (
            b'LIVE_ENTRY_MODE=model\0'
            b'AI_PAPER_MODEL_PATH=/models/latest-approved.json\0'
            b'TOKEN=opaque=value\0'
            b'\0'
        )
        self.assertEqual(
            parse_environ(payload),
            {
                b'LIVE_ENTRY_MODE': b'model',
                b'AI_PAPER_MODEL_PATH': b'/models/latest-approved.json',
                b'TOKEN': b'opaque=value',
            },
        )

    def test_invalid_entries_are_ignored(self):
        self.assertEqual(parse_environ(b'NO_SEPARATOR\0VALID=yes\0'), {b'VALID': b'yes'})


if __name__ == '__main__':
    unittest.main()
