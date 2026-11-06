"""Teacher-only drafts. Optimistic versions and replay-safe saves; never publish grades."""
import json
import re
import uuid
from utils import review_store, student_store
from utils.workspace_store import connection, timestamp


def view(conn, row):
    draft = conn.execute('SELECT * FROM student_attempt_drafts WHERE attempt_id=?', (row['id'],)).fetchone()
    if draft is None:
        return None
    return dict(json.loads(draft['payload']), revision=draft['revision'], updated_at=draft['updated_at'],
                stale=draft['base_revision'] != row['revision'])


def check(conn, row, value):
    draft = conn.execute('SELECT * FROM student_attempt_drafts WHERE attempt_id=?', (row['id'],)).fetchone()
    if value.get('draft_revision') != (draft['revision'] if draft else None) or (draft and draft['base_revision'] != row['revision']):
        student_store.fail('Черновик изменён в другой вкладке. Скачайте свои правки и откройте работу заново.', 'draft_conflict', 409)
    return draft


def save(owner, attempt_id, value):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = student_store.owned_attempt(conn, owner, attempt_id)
        if type(value.get('revision')) is not int or value['revision'] != row['revision'] or row['status'] not in ('submitted', 'needs_review', 'confirmed'):
            student_store.fail('Работа изменилась. Откройте её заново.', 'revision_conflict', 409)
        request_id = value.get('request_id')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9-]{32,36}', request_id):
            student_store.fail('Обновите страницу и повторите сохранение.')
        editable = dict(row)
        editable['answers'] = json.dumps(student_store.attempt_view(conn, row, True)['answers'])
        payload = review_store.editable(conn, owner, editable, value, False)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        previous = conn.execute('SELECT * FROM student_attempt_drafts WHERE attempt_id=?', (attempt_id,)).fetchone()
        # If a response was lost, the exact same request can be safely retried.
        if previous and previous['request_id'] == request_id:
            if previous['payload'] != encoded or previous['base_revision'] != row['revision']:
                student_store.fail('Содержание повторного запроса изменилось.', 'request_key_conflict', 409)
            return view(conn, row)
        check(conn, row, value)
        conn.execute('INSERT OR REPLACE INTO student_attempt_drafts VALUES(?,?,?,?,?,?)',
                     (attempt_id, row['revision'], uuid.uuid4().hex, request_id, encoded, timestamp()))
        return view(conn, row)


def discard(owner, attempt_id, value):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = student_store.owned_attempt(conn, owner, attempt_id)
        if type(value.get('revision')) is not int or value['revision'] != row['revision']:
            student_store.fail('Обновите работу перед удалением черновика.', 'revision_conflict', 409)
        check(conn, row, value)
        conn.execute('DELETE FROM student_attempt_drafts WHERE attempt_id=?', (attempt_id,))
