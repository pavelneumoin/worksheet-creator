"""Persistent user-owned materials and artifacts; every read includes the owner."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import uuid

from utils import db
from utils.gigachat_client import AIServiceError
from utils.worksheet import validate_worksheet, edition_code, text_field


@contextmanager
def connection():
    conn = sqlite3.connect(db.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def missing():
    raise AIServiceError('Материал не найден или уже удалён.', 'material_not_found', 404)


def result_links(row):
    if row is None:
        return None
    return {'artifact_id': row['id'], 'pdf_url': '/api/generated/' + row['pdf'],
            'keys_url': '/api/generated/' + row['answers'] if row['answers'] else None,
            'tex_url': '/api/generated/' + row['tex'] if row['tex'] else None,
            'marp_url': '/api/generated/' + row['marp'] if row['marp'] else None}


def material_row(conn, owner, row):
    if row is None:
        missing()
    artifact = conn.execute('SELECT * FROM artifacts WHERE owner_id=? AND material_id=? ORDER BY created_at DESC LIMIT 1',
                            (owner, row['id'])).fetchone()
    publication = conn.execute('SELECT id FROM library_publications WHERE material_id=? AND owner_id=?',
                               (row['id'], owner)).fetchone()
    origin = conn.execute('SELECT publication_id,author,title FROM material_origins WHERE material_id=?',
                          (row['id'],)).fetchone()
    meta = conn.execute('SELECT folder,archived FROM material_meta WHERE material_id=?', (row['id'],)).fetchone()
    versions = conn.execute('SELECT COUNT(*) FROM editions WHERE owner_id=? AND material_id=?', (owner, row['id'])).fetchone()[0]
    return {'id': row['id'], 'worksheet': json.loads(row['worksheet']), 'source': row['source'],
            'revision': row['revision'], 'updated': row['updated_at'], 'result': result_links(artifact),
            'publication_id': publication['id'] if publication else None,
            'origin': dict(origin) if origin else None,
            'folder': meta['folder'] if meta else '', 'archived': bool(meta['archived']) if meta else False,
            'edition_count': versions}


def list_materials(owner):
    with connection() as conn:
        rows = conn.execute('SELECT * FROM materials WHERE owner_id=? ORDER BY updated_at DESC LIMIT 500', (owner,)).fetchall()
        return [material_row(conn, owner, row) for row in rows]


def get_material(owner, material_id):
    with connection() as conn:
        return material_row(conn, owner, conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?',
                                                     (material_id, owner)).fetchone())


def put_material(owner, worksheet, source, material_id=None, revision=None, artifact_id=None, origin_material_id=None):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if material_id:
            current = conn.execute('SELECT revision FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone()
            if current is None:
                missing()
            if type(revision) is not int or revision != current['revision']:
                raise AIServiceError('Этот лист изменён на другом устройстве. Сохраните копию или откройте свежую версию.',
                                     'revision_conflict', 409)
        elif conn.execute('SELECT COUNT(*) FROM materials WHERE owner_id=?', (owner,)).fetchone()[0] >= 500:
            raise AIServiceError('Достигнут предел: 500 материалов. Удалите ненужные листы.', 'materials_limit', 409)
        origin = None
        if origin_material_id:
            if material_id or not conn.execute('SELECT 1 FROM materials WHERE id=? AND owner_id=?',
                                               (origin_material_id, owner)).fetchone():
                missing()
            origin = conn.execute('SELECT publication_id,author,title FROM material_origins WHERE material_id=?',
                                  (origin_material_id,)).fetchone()
        if artifact_id:
            artifact = conn.execute('SELECT material_id FROM artifacts WHERE id=? AND owner_id=?', (artifact_id, owner)).fetchone()
            if artifact is None or artifact['material_id'] not in (None, material_id):
                missing()
            edition = conn.execute('SELECT worksheet,material_id FROM editions WHERE id=? AND owner_id=?', (artifact_id, owner)).fetchone()
            if edition and validate_worksheet(json.loads(edition['worksheet'])) != validate_worksheet(worksheet):
                raise AIServiceError('PDF относится к другой версии. Соберите лист заново.', 'edition_mismatch', 409)
            if edition and edition['material_id'] not in (None, material_id):
                raise AIServiceError('Эта версия сохранена у исходного листа. Сохраните копию заданий и соберите её отдельно.', 'edition_material_mismatch', 409)
        now = timestamp()
        body = json.dumps(worksheet, ensure_ascii=False)
        if material_id:
            conn.execute('UPDATE materials SET worksheet=?,source=?,updated_at=?,revision=revision+1 WHERE id=? AND owner_id=?',
                         (body, source, now, material_id, owner))
            # Detach outdated files: the new revision must never show an old PDF.
            conn.execute('UPDATE artifacts SET material_id=NULL WHERE material_id=? AND owner_id=?', (material_id, owner))
        else:
            material_id = uuid.uuid4().hex
            conn.execute('INSERT INTO materials VALUES (?,?,?,?,1,?,?)', (material_id, owner, body, source, now, now))
            if origin:
                conn.execute('INSERT INTO material_origins VALUES (?,?,?,?)',
                             (material_id, origin['publication_id'], origin['author'], origin['title']))
        if artifact_id:
            conn.execute('UPDATE artifacts SET material_id=? WHERE id=? AND owner_id=?', (material_id, artifact_id, owner))
            conn.execute('UPDATE editions SET material_id=? WHERE id=? AND owner_id=? AND material_id IS NULL', (material_id, artifact_id, owner))
        return material_row(conn, owner, conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone())


def delete_material(owner, material_id, revision):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT revision FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone()
        if row is None:
            missing()
        if type(revision) is not int or revision != row['revision']:
            raise AIServiceError('Лист был изменён. Обновите список перед удалением.', 'revision_conflict', 409)
        if conn.execute('''SELECT 1 FROM assignments a JOIN editions e ON e.id=a.edition_id
                           WHERE e.material_id=? AND a.owner_id=? LIMIT 1''', (material_id, owner)).fetchone():
            raise AIServiceError('Этот лист назначен классу. Перенесите его в архив: версии и ответы нужны для истории работ.',
                                 'material_assigned', 409)
        ids = [r[0] for r in conn.execute('SELECT id FROM editions WHERE material_id=? AND owner_id=?', (material_id, owner))]
        files = list(conn.execute('SELECT pdf,answers,tex,marp FROM artifacts WHERE material_id=? AND owner_id=?', (material_id, owner)))
        for artifact_id in ids:
            files.extend(conn.execute('SELECT pdf,answers,tex,marp FROM artifacts WHERE id=? AND owner_id=?', (artifact_id, owner)))
            conn.execute('DELETE FROM artifacts WHERE id=? AND owner_id=?', (artifact_id, owner))
        conn.execute('DELETE FROM materials WHERE id=? AND owner_id=?', (material_id, owner))
        return list({name for row in files for name in row if name})


def organize_material(owner, material_id, folder, archived):
    folder = text_field(folder, 'Папка', 60)
    if type(archived) is not bool:
        raise AIServiceError('Выберите состояние материала.', 'invalid_archive', 400)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone()
        if row is None:
            missing()
        conn.execute('INSERT INTO material_meta VALUES (?,?,?) ON CONFLICT(material_id) DO UPDATE SET folder=excluded.folder,archived=excluded.archived',
                     (material_id, folder, int(archived)))
        return material_row(conn, owner, row)


def record_edition(conn, artifact_id, owner, material_id, worksheet, revision):
    conn.execute('INSERT INTO editions VALUES (?,?,?,?,?,?,?)',
                 (artifact_id, owner, material_id, json.dumps(worksheet, ensure_ascii=False), edition_code(worksheet), revision, timestamp()))


def list_editions(owner, material_id):
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone():
            missing()
        rows = conn.execute('SELECT e.*,a.pdf,a.answers,a.tex,a.marp FROM editions e JOIN artifacts a ON a.id=e.id WHERE e.owner_id=? AND e.material_id=? ORDER BY e.created_at DESC',
                            (owner, material_id)).fetchall()
        return [{'id': r['id'], 'code': r['code'], 'revision': r['revision'], 'created': r['created_at'],
                 'worksheet': json.loads(r['worksheet']), 'result': result_links(r)} for r in rows]


def add_artifact(owner, pdf, answers, tex, marp=None):
    with connection() as conn:
        artifact_id = uuid.uuid4().hex
        conn.execute('INSERT INTO artifacts (id,owner_id,material_id,pdf,answers,tex,created_at,marp) VALUES (?,?,NULL,?,?,?,?,?)',
                     (artifact_id, owner, pdf, answers, tex, timestamp(), marp))
        return result_links(conn.execute('SELECT * FROM artifacts WHERE id=? AND owner_id=?', (artifact_id, owner)).fetchone())


def owns_file(owner, filename):
    with connection() as conn:
        return conn.execute('SELECT 1 FROM artifacts WHERE owner_id=? AND (pdf=? OR answers=? OR tex=? OR marp=?)',
                            (owner, filename, filename, filename, filename)).fetchone() is not None
