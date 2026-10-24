"""Regress the real frozen QtCore failure caused by a foreign ICU DLL."""

import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == 'nt', 'Windows ICU packaging rule')
class TestWindowsICUPackaging(unittest.TestCase):
    def test_foreign_icu_cannot_shadow_the_windows_implementation(self):
        spec = importlib.util.spec_from_file_location(
            'release_builder', Path(__file__).resolve().parents[1] / 'scripts' / 'build.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory(prefix='modelpaintpal-icu-') as directory:
            target = Path(directory)
            internal = target / '_internal'
            (internal / 'PySide6').mkdir(parents=True)
            core = internal / 'PySide6' / 'Qt6Core.dll'
            core.write_bytes(b'Qt import-table fixture')
            shadow = internal / 'icuuc.dll'
            shadow.write_bytes(b'foreign ICU with versioned, incompatible exports')
            # The dependency contract of Qt 6.10+ uses unsuffixed Windows ICU symbols.
            table = SimpleNamespace(DIRECTORY_ENTRY_IMPORT=[SimpleNamespace(
                dll=b'icuuc.dll', imports=[SimpleNamespace(name=b'ucnv_open')])])
            with patch('pefile.PE') as parser:
                parser.return_value.__enter__.return_value = table
                builder._check_windows_icu(target)
            self.assertFalse(shadow.exists())
            self.assertTrue(core.exists())


if __name__ == '__main__':
    unittest.main()
