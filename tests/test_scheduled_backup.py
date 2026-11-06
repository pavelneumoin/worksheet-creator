import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('scheduled_backup', Path(__file__).resolve().parents[1] / 'deploy/scheduled_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class ScheduledBackupTests(unittest.TestCase):
    def archive(self, root, corrupt=False, secret=False):
        database = root / 'fixture.db'
        with closing(sqlite3.connect(database)) as conn:
            conn.execute('CREATE TABLE sessions(id TEXT)')
            if secret:
                conn.execute("INSERT INTO sessions VALUES ('must-not-survive')")
            conn.commit()
        data = database.read_bytes()
        files = {'worksheets.db': {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}}
        path = root / 'backup.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('worksheets.db', data if not corrupt else data + b'changed')
            archive.writestr('manifest.json', json.dumps({'format': 'listok-backup-v1', 'files': files}))
        return path

    def test_real_sqlite_archive_and_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(backup.verify_archive(self.archive(Path(td)))['files'], 1)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                backup.verify_archive(self.archive(Path(td), corrupt=True))

    def test_transient_access_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                backup.verify_archive(self.archive(Path(td), secret=True))

    def test_retention_only_own_archives(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for day in range(1, 6):
                (root / f'listok-2026110{day}T041500Z-1234abcd.zip').write_bytes(b'fixture')
            foreign = root / 'important.zip'
            foreign.write_bytes(b'keep')
            self.assertEqual(backup.prune(root, 3), 2)
            self.assertTrue(foreign.exists())
            self.assertTrue((root / 'listok-20261105T041500Z-1234abcd.zip').exists())
            with self.assertRaises(ValueError):
                backup.prune(root, 2)

    def test_failed_backup_preserves_existing_copies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / 'listok-20261101T041500Z-1234abcd.zip'
            old.write_bytes(b'previous archive')
            with patch.object(backup.subprocess, 'run', side_effect=OSError('Docker unavailable')):
                with self.assertRaises(OSError):
                    backup.run_backup(root, 'listok-listok-1')
            self.assertEqual(old.read_bytes(), b'previous archive')


if __name__ == '__main__':
    unittest.main()
