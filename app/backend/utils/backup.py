"""Consistent local backup; restore only into a new directory, never over live data."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from urllib.parse import urlsplit

from utils import db, latex


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def artifact_names(conn):
    return {name for row in conn.execute('SELECT pdf,answers,tex,marp FROM artifacts') for name in row if name} | legacy_names(conn)


def legacy_names(conn):
    names = set()
    for row in conn.execute('SELECT pdf_url,keys_url FROM history'):
        for url in row:
            if url:
                name = PurePosixPath(urlsplit(url).path).name
                if re.fullmatch(r'[A-Za-z0-9_-]+\.pdf', name):
                    names.add(name)
    return names


def review_photo_names(conn):
    # Older backups predate photo reviews and remain restorable.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reviews'").fetchone():
        return set()
    return {f"review_photos/{row[0]}/{i}.jpg" for row in conn.execute('SELECT id,photo_count FROM reviews') for i in range(row[1])}


def fail_restored_reviews(conn):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reviews'").fetchone():
        conn.execute("UPDATE reviews SET status='failed' WHERE status='processing'")


def create_backup(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Архив уже существует. Выберите новое имя.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='listok-backup-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        # Hold a write reservation while taking the DB snapshot AND copying its files.
        guard = sqlite3.connect(db.DB_PATH, timeout=30)
        try:
            guard.execute('BEGIN IMMEDIATE')
            source = sqlite3.connect(db.DB_PATH, timeout=30)
            snapshot = sqlite3.connect(stage / 'worksheets.db')
            try:
                source.backup(snapshot)
                names = artifact_names(snapshot)
                photos = review_photo_names(snapshot)
                fail_restored_reviews(snapshot)
                snapshot.execute('DELETE FROM download_tickets')
                snapshot.execute('DELETE FROM sessions')
                snapshot.execute('DELETE FROM workers')
                # Inputs are intentionally excluded; never replay paid requests on restore.
                snapshot.execute("UPDATE jobs SET status='failed',error='Сервис восстановлен из копии. Повторите действие вручную.',error_code='backup_restored',finished_at=?,updated_at=?,claim=NULL WHERE status IN ('queued','running')", (time.time(), time.time()))
                snapshot.commit()
                snapshot.execute('VACUUM')
            finally:
                source.close(); snapshot.close()
            generated = Path(latex.OUTPUT_DIR).resolve()
            (stage / 'generated').mkdir()
            for name in sorted(names):
                if not re.fullmatch(r'[A-Za-z0-9_-]+\.(pdf|tex|zip)', name):
                    raise ValueError('Небезопасное имя файла в базе.')
                source_path = generated / name
                if source_path.is_symlink() or not source_path.is_file():
                    raise ValueError('В базе есть отсутствующий файл. Сначала восстановите целостность хранилища.')
                shutil.copyfile(source_path, stage / 'generated' / name)
            for name in sorted(photos):
                if not re.fullmatch(r'review_photos/[a-f0-9]{32}/[0-9]\.jpg', name):
                    raise ValueError('Небезопасное имя фотографии в базе.')
                source_path = Path(db.DB_PATH).resolve().parent.joinpath(*PurePosixPath(name).parts)
                if source_path.is_symlink() or not source_path.is_file():
                    raise ValueError('Фотография из базы отсутствует. Сначала восстановите целостность хранилища.')
                target = stage.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, target)
        finally:
            guard.rollback(); guard.close()
        files = sorted(p for p in stage.rglob('*') if p.is_file())
        manifest = {'format': 'listok-backup-v1', 'created_at': time.time(),
                    'files': {p.relative_to(stage).as_posix(): {'sha256': digest(p), 'size': p.stat().st_size} for p in files}}
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        archive_path = stage / 'backup.zip'
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for p in files + [stage / 'manifest.json']:
                archive.write(p, p.relative_to(stage).as_posix())
        # Exclusive final creation prevents accidental overwrite even during concurrent CLI calls.
        with destination.open('xb') as stream, archive_path.open('rb') as source:
            shutil.copyfileobj(source, stream)
    return {'archive': str(destination), 'files': len(files), 'sha256': digest(destination)}


def restore_backup(archive_path, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Восстановление разрешено только в новый каталог. Рабочая база не перезаписывается.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='listok-restore-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if len(names) != len(set(names)) or len(names) > 100000 or sum(i.file_size for i in entries) > 5 * 1024**3:
                raise ValueError('Некорректный или слишком большой архив.')
            for name in names:
                if name not in ('manifest.json', 'worksheets.db') and not re.fullmatch(r'generated/[A-Za-z0-9_-]+\.(pdf|tex|zip)|review_photos/[a-f0-9]{32}/[0-9]\.jpg', name):
                    raise ValueError('Недопустимый путь в архиве.')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size > 20_000_000:
                raise ValueError('Нет корректного манифеста.')
            manifest = json.loads(archive.read('manifest.json'))
            expected = manifest.get('files', {})
            if manifest.get('format') != 'listok-backup-v1' or set(names) != set(expected) | {'manifest.json'} or 'worksheets.db' not in expected:
                raise ValueError('Неполный архив.')
            for name, meta in expected.items():
                target = stage.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open('xb') as stream:
                    shutil.copyfileobj(source, stream)
                if target.stat().st_size != meta['size'] or digest(target) != meta['sha256']:
                    raise ValueError('Контрольная сумма не совпала. Архив повреждён.')
        conn = sqlite3.connect(stage / 'worksheets.db')
        try:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Проверка базы не пройдена.')
            if {f'generated/{n}' for n in artifact_names(conn)} != {n for n in expected if n.startswith('generated/')}:
                raise ValueError('Состав файлов не соответствует базе.')
            if review_photo_names(conn) != {n for n in expected if n.startswith('review_photos/')}:
                raise ValueError('Состав фотографий не соответствует базе.')
            fail_restored_reviews(conn)
            conn.execute('DELETE FROM download_tickets'); conn.execute('DELETE FROM sessions'); conn.execute('DELETE FROM workers')
            conn.execute("UPDATE jobs SET status='failed',error_code='backup_restored',error='Восстановлено из копии. Повторите вручную.',finished_at=? WHERE status IN ('queued','running')", (time.time(),))
            conn.commit()
        finally:
            conn.close()
        # Rename only this verified staging directory to a new sibling destination.
        if destination.exists():
            raise ValueError('Каталог назначения уже появился.')
        stage.rename(destination)
    return {'directory': str(destination), 'files': len(expected)}


def cleanup_generated(apply=False, days=30):
    """Keep editions forever until the teacher deletes them; only purge stale loose files."""
    if days < 7:
        raise ValueError('Срок хранения должен быть не меньше 7 дней.')
    cutoff = time.time() - days * 86400
    from utils.workspace_store import connection
    from datetime import datetime, timezone
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        stale = list(conn.execute('SELECT id FROM artifacts WHERE material_id IS NULL AND id NOT IN (SELECT id FROM editions) AND created_at<?',
                                  (datetime.fromtimestamp(cutoff, timezone.utc).isoformat(),)))
        retained = {name for row in conn.execute('SELECT pdf,answers,tex,marp FROM artifacts WHERE id NOT IN (SELECT id FROM artifacts WHERE material_id IS NULL AND id NOT IN (SELECT id FROM editions) AND created_at<?)',
                   (datetime.fromtimestamp(cutoff, timezone.utc).isoformat(),)) for name in row if name}
        active = {'job_' + r[0] for r in conn.execute("SELECT id FROM jobs WHERE status IN ('queued','running')")}
        retained.update(legacy_names(conn))
        root = Path(latex.OUTPUT_DIR).resolve()
        files = [p for p in root.iterdir() if p.is_file() and not p.is_symlink()
                 and re.fullmatch(r'[A-Za-z0-9_-]+\.(pdf|tex|zip|log)', p.name)
                 and p.name not in retained and p.stat().st_mtime < cutoff
                 and not any(p.name.startswith(prefix) for prefix in active)]
        if apply:
            for row in stale:
                conn.execute('DELETE FROM artifacts WHERE id=?', (row[0],))
    # DB references are removed before disk files. A failure leaves removable garbage, never a dangling reference.
    if apply:
        for p in files:
            p.unlink(missing_ok=True)
    return {'applied': apply, 'artifacts': len(stale), 'files': len(files), 'bytes': sum(p.stat().st_size for p in files) if not apply else None}
