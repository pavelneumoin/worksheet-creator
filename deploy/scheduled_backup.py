"""Host-side daily backup of the running application. Python standard library only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile

NAME = re.compile(r'listok-\d{8}T\d{6}Z-[a-f0-9]{8}\.zip\Z')


def verify_archive(path):
    """Read every byte, validate the manifest and SQLite without restoring live state."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if len(names) != len(set(names)) or len(names) > 100000:
            raise ValueError('Duplicate entries or too many files')
        if sum(item.file_size for item in entries) > 5 * 1024**3:
            raise ValueError('Archive is too large')
        if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 20_000_000:
            raise ValueError('Missing or oversized manifest')
        manifest = json.loads(archive.read('manifest.json'))
        expected = manifest.get('files', {})
        if (manifest.get('format') != 'listok-backup-v1'
                or set(names) != set(expected) | {'manifest.json'} or 'worksheets.db' not in expected):
            raise ValueError('Incomplete archive')
        for name, meta in expected.items():
            with archive.open(name) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if archive.getinfo(name).file_size != meta['size'] or digest != meta['sha256']:
                raise ValueError('File checksum mismatch')
        with tempfile.TemporaryDirectory(prefix='listok-backup-check-') as temporary:
            database = Path(temporary) / 'worksheets.db'
            # Extract only the fixed database name, never an archive-provided path.
            database.write_bytes(archive.read('worksheets.db'))
            connection = sqlite3.connect(database)
            try:
                if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite integrity failed')
                if connection.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('SQLite foreign keys failed')
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('sessions', 'bot_login_tokens', 'student_notifications'):
                    if table in tables and connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]:
                        raise ValueError('Backup contains transient access or delivery state')
            finally:
                connection.close()
    with Path(path).open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'files': len(expected), 'sha256': sha, 'bytes': Path(path).stat().st_size}


def prune(directory, keep):
    """Called only after a new backup passes verification; leave all unrelated files alone."""
    if keep < 3:
        raise ValueError('Keep at least three backups')
    backups = sorted((p for p in Path(directory).iterdir()
                      if NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()),
                     key=lambda p: p.name, reverse=True)
    for path in backups[keep:]:
        path.unlink()
    return len(backups[keep:])


def run_backup(directory, container, keep=7):
    if keep < 3 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', container):
        raise ValueError('Invalid retention or container name')
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('Backup directory must not be a symlink')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = directory.resolve()
    os.chmod(directory, 0o700)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    name = f'listok-{timestamp}-{uuid.uuid4().hex[:8]}.zip'
    target = directory / name
    pending = directory / (name + '.part')
    remote = '/tmp/' + name
    subprocess.run(['docker', 'exec', container, 'python', 'scripts/manage_storage.py', 'backup', remote],
                   check=True, capture_output=True, timeout=300)
    try:
        with pending.open('xb') as stream:
            os.chmod(pending, 0o600)
            subprocess.run(['docker', 'exec', container, 'cat', remote],
                           stdout=stream, stderr=subprocess.PIPE, check=True, timeout=300)
            stream.flush()
            os.fsync(stream.fileno())
        result = verify_archive(pending)
        pending.rename(target)
        result.update(file=name, created_at=datetime.now(timezone.utc).isoformat(),
                      removed=prune(directory, keep), verified=True)
        status = directory / 'latest.json'
        # Directory is root-only; status contains no pupil data or access keys.
        temporary_status = directory / 'latest.json.part'
        temporary_status.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        os.chmod(temporary_status, 0o600)
        temporary_status.replace(status)
        return result
    finally:
        pending.unlink(missing_ok=True)
        subprocess.run(['docker', 'exec', container, 'python', '-c',
                        'from pathlib import Path; import sys; Path(sys.argv[1]).unlink(missing_ok=True)', remote],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def main():
    parser = argparse.ArgumentParser(description='Verified backup of a running ListOK container')
    parser.add_argument('--directory', required=True)
    parser.add_argument('--container', default='listok-listok-1')
    parser.add_argument('--keep', type=int, default=7)
    args = parser.parse_args()
    os.umask(0o077)
    # systemd serializes this service; flock also guards manual invocations on Linux.
    import fcntl
    with open('/run/lock/listok-backup.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(run_backup(args.directory, args.container, args.keep)))


if __name__ == '__main__':
    main()
