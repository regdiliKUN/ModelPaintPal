import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(os.name == 'nt', 'Native Windows hotkey lifetime')
class TestHotkeyLifecycle(unittest.TestCase):
    def test_immediate_stop_does_not_leave_a_native_listener_alive(self):
        probe = Path(__file__).parent / 'probes' / 'hotkey_restart.py'
        result = subprocess.run([sys.executable, '-X', 'utf8', str(probe)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('5 immediate native listener stops completed', result.stdout)
