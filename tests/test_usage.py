import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.usage import UsageLedger


class TestUsageLedger(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / 'usage.json'

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_and_month_total(self):
        ledger = UsageLedger(self.path)
        ledger.record('deepl_oneshot', 5000)
        ledger.record('deepl_oneshot', 2500)
        self.assertEqual(ledger.month_total('deepl_oneshot'), 7500)

    def test_persists_across_instances(self):
        UsageLedger(self.path).record('baidu', 100)
        reloaded = UsageLedger(self.path)
        self.assertEqual(reloaded.month_total('baidu'), 100)

    def test_zero_and_negative_ignored(self):
        ledger = UsageLedger(self.path)
        ledger.record('tencent_tmt', 0)
        ledger.record('tencent_tmt', -5)
        self.assertEqual(ledger.month_total('tencent_tmt'), 0)

    def test_unknown_provider_zero(self):
        ledger = UsageLedger(self.path)
        self.assertEqual(ledger.month_total('nobody'), 0)


if __name__ == '__main__':
    unittest.main()
