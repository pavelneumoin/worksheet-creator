"""Short-lived OCR files outside SQLite/backups; idempotent code-only imports."""
import json
import os
from pathlib import Path
import re
import time
import uuid

from utils import db, class_store, job_store, roster_ai
from utils.gigachat_client import AIServiceError
from utils.workspace_store import connection, timestamp

TTL = 15 * 60


def result_path(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise AIServiceError('Список не найден.', 'roster_not_found', 404)
    directory = Path(db.DB_PATH).resolve().parent / 'roster_results'
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / (job_id + '.json')


def complete(job_id, class_id, output):
    result = roster_ai.validate(output)
    if not result['rows']:
        raise AIServiceError('Список учеников не найден.', 'roster_empty', 400)
    expires = time.time() + TTL
    path = result_path(job_id)
    temporary = path.with_suffix('.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as stream:
        json.dump({'rows': result['rows'], 'expires_at': expires}, stream, ensure_ascii=False)
    temporary.replace(path)
    return {'class_id': class_id, 'expires_at': expires, 'row_count': len(result['rows'])}


def get(owner, job_id, discard=False):
    with connection() as conn:
        job = job_store._owned(conn, owner, job_id)
        if job['kind'] != 'roster_recognize':
            raise AIServiceError('Список не найден.', 'roster_not_found', 404)
        if job['status'] != 'succeeded':
            raise AIServiceError('Список ещё не готов.', 'roster_not_ready', 409)
        meta = json.loads(job['result'])
        class_store.owned_class(conn, owner, meta['class_id'])
        path = result_path(job_id)
        if discard:
            path.unlink(missing_ok=True)
            return {'discarded': True}
        try:
            if meta['expires_at'] <= time.time():
                path.unlink(missing_ok=True)
                raise FileNotFoundError()
            result = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise AIServiceError('Временный список удалён. Если он не открыт на странице, распознайте фото заново.', 'roster_expired', 410)
        return {**meta, 'rows': roster_ai.validate({'rows': result['rows'], 'too_many': False})['rows']}


def maintain(conn, now):
    conn.execute("""UPDATE jobs SET status='failed',error='Время обработки списка истекло. Загрузите фото заново.',
                 error_code='roster_expired',finished_at=?,updated_at=?
                 WHERE kind='roster_recognize' AND status IN ('queued','running') AND created_at<?""", (now, now, now - TTL))
    directory = Path(db.DB_PATH).resolve().parent / 'roster_results'
    if directory.is_dir():
        for path in directory.iterdir():
            try:
                if re.fullmatch(r'[a-f0-9]{32}\.(json|tmp)', path.name) and path.stat().st_mtime < now - TTL:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass  # The owner may discard a result while cleanup is listing it.


def import_codes(owner, class_id, data):
    if set(data) != {'request_key', 'revision', 'count'}:
        raise AIServiceError('Передайте количество и версию класса. Имена в базе не сохраняются.', 'student_names_disabled', 400)
    key = job_store.validate_key(data['request_key'])
    amount = data['count']
    if type(amount) is not int or not 1 <= amount <= 100 or type(data['revision']) is not int:
        raise AIServiceError('Добавьте от 1 до 100 учеников.', 'invalid_class', 400)
    # A retry after reloading sees the new class revision but must get the same codes.
    signature = job_store.fingerprint('roster_codes', {'class_id': class_id, 'count': amount})
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        class_store.owned_class(conn, owner, class_id)
        previous = conn.execute('SELECT * FROM roster_imports WHERE owner_id=? AND request_key=?', (owner, key)).fetchone()
        if previous:
            if previous['fingerprint'] != signature:
                raise AIServiceError('Этот запрос уже использован для другого списка.', 'request_key_conflict', 409)
            ids = json.loads(previous['student_ids'])
        else:
            class_store.owned_class(conn, owner, class_id, data, active=True)
            existing = {class_store.student_code(r['id']) for r in conn.execute('SELECT id FROM students WHERE class_id=?', (class_id,))}
            if len(existing) + amount > 200:
                raise AIServiceError('В классе можно хранить до 200 записей, включая архив.', 'student_limit', 409)
            ids = []
            while len(ids) < amount:
                ident = uuid.uuid4().hex
                if class_store.student_code(ident) not in existing:
                    ids.append(ident); existing.add(class_store.student_code(ident))
            now = timestamp()
            conn.executemany('INSERT INTO students (id,class_id,name,created_at) VALUES (?,?,?,?)',
                             [(ident, class_id, class_store.student_code(ident), now) for ident in ids])
            class_store.touch(conn, class_id)
            conn.execute('INSERT INTO roster_imports VALUES (?,?,?,?,?,?)', (owner, key, class_id, signature, json.dumps(ids), now))
        return {'classroom': class_store.class_detail(conn, owner, class_id),
                'students': [{'id': ident, 'code': class_store.student_code(ident)} for ident in ids], 'reused': bool(previous)}
