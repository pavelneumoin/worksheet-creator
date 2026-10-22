"""Durable SQLite queue with owner isolation, idempotency and fenced completion."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from utils import db
from utils.gigachat_client import AIServiceError
from utils.worksheet import validate_worksheet
from utils.workspace_store import connection, result_links, timestamp

ACTIVE = ('queued', 'running')
TERMINAL = ('succeeded', 'failed', 'cancelled')
LANES = {'recognize': 'ai', 'variant': 'ai', 'compile': 'compile'}
LABELS = {'recognize': 'Распознаём задания и готовим ответы', 'variant': 'Готовим новый вариант', 'compile': 'Собираем лист, ответы и Marp'}
LEASE_SECONDS = 45
RETENTION_SECONDS = 7 * 86400


def root():
    directory = Path(os.environ.get('LISTOK_JOBS_DIR') or (Path(db.DB_PATH).resolve().parent / 'jobs')).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def job_directory(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('Invalid job directory')
    parent = root()
    target = (parent / job_id).resolve()
    if target.parent != parent:
        raise ValueError('Job path escaped its directory')
    return target


def remove_inputs(job_id):
    target = job_directory(job_id)
    if target.exists():
        shutil.rmtree(target)


def fingerprint(kind, payload, image_paths=()):
    digest = hashlib.sha256(json.dumps([kind, payload], sort_keys=True, ensure_ascii=False).encode())
    for path in image_paths:
        file_digest = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                file_digest.update(chunk)
        digest.update(file_digest.digest())
    return digest.hexdigest()


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
        raise AIServiceError('Обновите страницу и повторите действие.', 'invalid_request_key', 400)
    return key


def _public(row, conn):
    position = 0
    if row['status'] == 'queued':
        position = conn.execute("SELECT COUNT(*) FROM jobs WHERE lane=? AND status='queued' AND (created_at<? OR (created_at=? AND id<=?))",
                                (row['lane'], row['created_at'], row['created_at'], row['id'])).fetchone()[0]
    return {'id': row['id'], 'request_key': row['request_key'], 'kind': row['kind'], 'status': row['status'], 'position': position,
            'label': LABELS[row['kind']], 'created_at': row['created_at'], 'started_at': row['started_at'],
            'result': json.loads(row['result']) if row['result'] else None,
            'error': row['error'], 'error_code': row['error_code']}


def _owned(conn, owner, job_id):
    row = conn.execute('SELECT * FROM jobs WHERE id=? AND owner_id=?', (job_id, owner)).fetchone()
    if row is None:
        raise AIServiceError('Задача не найдена в вашем профиле.', 'job_not_found', 404)
    return row


def get_job(owner, job_id):
    with connection() as conn:
        return _public(_owned(conn, owner, job_id), conn)


def list_jobs(owner):
    with connection() as conn:
        rows = conn.execute('SELECT * FROM jobs WHERE owner_id=? AND acknowledged=0 ORDER BY created_at DESC LIMIT 50', (owner,)).fetchall()
        return [_public(row, conn) for row in rows]


def workers_ready(lane=None):
    with connection() as conn:
        rows = conn.execute('SELECT DISTINCT lane FROM workers WHERE heartbeat>?', (time.time() - 20,)).fetchall()
    alive = {row['lane'] for row in rows}
    return lane in alive if lane else {'ai': 'ai' in alive, 'compile': 'compile' in alive}


def heartbeat(worker, lane, job_id=None, claim=None):
    now = time.time()
    with connection() as conn:
        conn.execute('INSERT INTO workers VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat', (worker, lane, now))
        if job_id:
            conn.execute("UPDATE jobs SET heartbeat=?,updated_at=? WHERE id=? AND claim=? AND status='running'", (now, now, job_id, claim))


def submit(owner, kind, request_key, payload, image_paths=(), require_worker=True):
    validate_key(request_key)
    if kind not in LANES:
        raise AIServiceError('Неизвестное действие.', 'invalid_job_kind', 400)
    signature = fingerprint(kind, payload, image_paths)
    job_id = uuid.uuid4().hex
    directory = job_directory(job_id)
    created = False
    try:
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT * FROM jobs WHERE owner_id=? AND request_key=?', (owner, request_key)).fetchone()
            if previous:
                if previous['fingerprint'] != signature:
                    raise AIServiceError('Этот запрос уже использован для другого содержания. Повторите действие заново.', 'request_key_conflict', 409)
                return _public(previous, conn), False
            if require_worker and not conn.execute('SELECT 1 FROM workers WHERE lane=? AND heartbeat>?', (LANES[kind], time.time() - 20)).fetchone():
                raise AIServiceError('Обработка временно недоступна. Сохраните черновик и повторите позже.', 'worker_unavailable', 503)
            if conn.execute("SELECT 1 FROM jobs WHERE owner_id=? AND status IN ('queued','running')", (owner,)).fetchone():
                raise AIServiceError('У вас уже есть задача. Дождитесь её результата — он появится в разделе «Задачи».', 'owner_job_limit', 429)
            if conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 30:
                raise AIServiceError('Сейчас много запросов. Попробуйте через несколько минут.', 'queue_full', 429)
            if kind != 'compile' and conn.execute('SELECT COUNT(*) FROM materials WHERE owner_id=?', (owner,)).fetchone()[0] >= 500:
                raise AIServiceError('Удалите ненужный материал: в профиле уже 500 листов.', 'materials_limit', 409)
            # Validate the saved snapshot in the same transaction as enqueueing.
            material_id = payload.get('material_id')
            if material_id:
                material = conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone()
                if material is None:
                    raise AIServiceError('Сохранённый лист не найден.', 'material_not_found', 404)
                if (type(payload.get('revision')) is not int or material['revision'] != payload['revision']
                        or json.loads(material['worksheet']) != payload['worksheet']):
                    raise AIServiceError('Лист изменился. Откройте свежую версию перед обработкой.', 'revision_conflict', 409)
            directory.mkdir()
            created = True
            stored = dict(payload)
            if material_id:
                stored['source'] = material['source']
                origin = conn.execute('SELECT author,title FROM material_origins WHERE material_id=?', (material_id,)).fetchone()
                stored['origin'] = dict(origin) if origin else None
            stored['images'] = []
            for i, image in enumerate(image_paths):
                name = str(i) + Path(image).suffix.lower()
                shutil.copyfile(image, directory / name)
                stored['images'].append(name)
            now = time.time()
            conn.execute('''INSERT INTO jobs (id,owner_id,kind,lane,request_key,fingerprint,payload,status,created_at,updated_at)
                            VALUES (?,?,?,?,?,?,?,'queued',?,?)''',
                         (job_id, owner, kind, LANES[kind], request_key, signature, json.dumps(stored, ensure_ascii=False), now, now))
            result = _public(_owned(conn, owner, job_id), conn)
        return result, True
    except BaseException:
        if created:
            remove_inputs(job_id)
        raise


def claim_next(lane):
    if lane not in ('ai', 'compile'):
        raise ValueError('Invalid lane')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM jobs WHERE lane=? AND status='running'", (lane,)).fetchone():
            return None
        row = conn.execute("SELECT * FROM jobs WHERE lane=? AND status='queued' ORDER BY created_at,id LIMIT 1", (lane,)).fetchone()
        if row is None:
            return None
        now, claim = time.time(), uuid.uuid4().hex
        conn.execute("UPDATE jobs SET status='running',claim=?,started_at=?,heartbeat=?,updated_at=? WHERE id=?", (claim, now, now, now, row['id']))
        return dict(conn.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())


def fail(job_id, claim, message, code):
    with connection() as conn:
        now = time.time()
        return bool(conn.execute("UPDATE jobs SET status='failed',error=?,error_code=?,finished_at=?,updated_at=? WHERE id=? AND claim=? AND status='running'",
                                 (message, code, now, now, job_id, claim)).rowcount)


def complete(job, output):
    """Commit saved material/artifact and result together; a stale worker cannot publish."""
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute("SELECT * FROM jobs WHERE id=? AND claim=? AND status='running'", (job['id'], job['claim'])).fetchone()
        if current is None:
            return False
        payload, now = json.loads(current['payload']), timestamp()
        owner, job_id = current['owner_id'], current['id']
        if current['kind'] == 'compile':
            # All file names are deterministic and supplied by our worker, never by a client.
            base = 'job_' + job_id
            conn.execute('INSERT INTO artifacts (id,owner_id,pdf,answers,tex,created_at,marp) VALUES (?,?,?,?,?,?,?)',
                         (job_id, owner, base + '.pdf', base + '_keys.pdf', base + '.tex', now, base + '_marp.zip'))
            material = conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?', (payload['material_id'], owner)).fetchone()
            attached = material is not None and material['revision'] == payload['revision']
            if attached:
                conn.execute('UPDATE artifacts SET material_id=NULL WHERE material_id=? AND owner_id=?', (material['id'], owner))
                conn.execute('UPDATE artifacts SET material_id=? WHERE id=?', (material['id'], job_id))
                conn.execute('UPDATE materials SET updated_at=? WHERE id=?', (now, material['id']))
            result = {'worksheet': payload['worksheet'], 'source': payload.get('source', 'manual'),
                      'material_id': material['id'] if attached else None, 'attached': attached,
                      **result_links(conn.execute('SELECT * FROM artifacts WHERE id=?', (job_id,)).fetchone())}
        else:
            worksheet = validate_worksheet(output['worksheet'])
            conn.execute('INSERT INTO materials VALUES (?,?,?,?,1,?,?)',
                         (job_id, owner, json.dumps(worksheet, ensure_ascii=False), 'ai_draft', now, now))
            if payload.get('material_id'):
                origin = conn.execute('SELECT * FROM material_origins WHERE material_id=?', (payload['material_id'],)).fetchone()
                if origin:
                    conn.execute('INSERT INTO material_origins VALUES (?,?,?,?)', (job_id, origin['publication_id'], origin['author'], origin['title']))
            result = {'material_id': job_id}
        completed = time.time()
        conn.execute("UPDATE jobs SET status='succeeded',result=?,finished_at=?,updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), completed, completed, job_id))
        return True


def acknowledge(owner, job_id):
    with connection() as conn:
        row = _owned(conn, owner, job_id)
        if row['status'] not in TERMINAL:
            raise AIServiceError('Задача ещё выполняется.', 'job_active', 409)
        conn.execute('UPDATE jobs SET acknowledged=1 WHERE id=? AND owner_id=?', (job_id, owner))


def cancel(owner, job_id):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _owned(conn, owner, job_id)
        if row['status'] == 'running':
            raise AIServiceError('Обработка уже началась. Можно закрыть приложение — результат сохраним в профиле.', 'job_running', 409)
        if row['status'] == 'queued':
            now = time.time()
            conn.execute("UPDATE jobs SET status='cancelled',finished_at=?,updated_at=? WHERE id=?", (now, now, job_id))
    if row['status'] == 'queued':
        remove_inputs(job_id)
    return get_job(owner, job_id)


def maintain():
    now = time.time()
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("""UPDATE jobs SET status='failed',error='Обработка прервалась. Повторите действие вручную; автоматического повторного запроса к ИИ не было.',
                        error_code='worker_interrupted',finished_at=?,updated_at=? WHERE status='running' AND heartbeat<?""", (now, now, now - LEASE_SECONDS))
        conn.execute("""UPDATE jobs SET status='failed',error='Время ожидания истекло. Повторите действие.',error_code='queue_expired',finished_at=?,updated_at=?
                        WHERE status='queued' AND created_at<?""", (now, now, now - 86400))
        terminal = [r['id'] for r in conn.execute("SELECT id FROM jobs WHERE status IN ('succeeded','failed','cancelled')")]
        conn.execute("DELETE FROM jobs WHERE finished_at<?", (now - RETENTION_SECONDS,))
        conn.execute('DELETE FROM workers WHERE heartbeat<?', (now - 86400,))
    for job_id in terminal:
        try:
            remove_inputs(job_id)
        except OSError:
            pass  # A just-killed Windows process may release a handle on the next pass.
