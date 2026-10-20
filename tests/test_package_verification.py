import os
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from backend.package_verification import build_package


class VerificationPackageTests(unittest.TestCase):
    def test_archive_is_stable_when_source_timestamps_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "backend"
            source.mkdir()
            names = ("lambda_verify.py", "verification.py", "admin_auth.py", "organizations.py")
            for name in names:
                (source / name).write_bytes(f"# {name}\n".encode())

            first = root / "first.zip"
            second = root / "second.zip"
            build_package(root, first)
            for name in names:
                os.utime(source / name, (1700000000, 1700000000))
            build_package(root, second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            with ZipFile(second) as archive:
                self.assertEqual(archive.namelist(), list(names))
                self.assertTrue(all(info.date_time == (2026, 1, 1, 0, 0, 0)
                                    for info in archive.infolist()))
