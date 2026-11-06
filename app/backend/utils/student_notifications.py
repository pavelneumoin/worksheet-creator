"""Transactional return notifications. Unknown delivery is not automatically replayed."""
import re
import time
import uuid
from utils.workspace_store import connection


def enqueue(conn, attempt):
    real = all(re.fullmatch(r'max:[1-9][0-9]*', attempt[k]) for k in ('owner_id', 'user_id'))
    now = time.time()
    conn.execute('''INSERT OR IGNORE INTO student_notifications
        (id,attempt_id,attempt_revision,user_id,status,due_at,updated_at) VALUES(?,?,?,?,?,?,?)''',
        (uuid.uuid4().hex, attempt['id'], attempt['revision'], attempt['user_id'], 'queued' if real else 'demo', now, now))


def poll(client):
    from utils.max_bot import APIError, app_origin
    now = time.time()
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE student_notifications SET status='unknown',updated_at=? WHERE status='sending' AND updated_at<?", (now, now-120))
        row = conn.execute("SELECT * FROM student_notifications WHERE status='queued' AND due_at<=? ORDER BY due_at LIMIT 1", (now,)).fetchone()
        if row is None:
            return False
        valid = conn.execute('''SELECT a.assignment_id FROM student_attempts a JOIN student_links l ON l.student_id=a.student_id
            JOIN assignments w ON w.id=a.assignment_id JOIN classrooms c ON c.id=w.class_id JOIN students s ON s.id=a.student_id
            WHERE a.id=? AND a.revision=? AND a.status='returned' AND a.user_id=? AND l.user_id=a.user_id
            AND w.status='active' AND c.archived=0 AND s.archived=0
            AND NOT EXISTS(SELECT 1 FROM student_attempts n WHERE n.assignment_id=a.assignment_id AND n.student_id=a.student_id AND n.number>a.number)''',
            (row['attempt_id'], row['attempt_revision'], row['user_id'])).fetchone()
        if not valid:
            conn.execute("UPDATE student_notifications SET status='cancelled',updated_at=? WHERE id=?", (now,row['id']))
            return True
        conn.execute("UPDATE student_notifications SET status='sending',tries=tries+1,updated_at=? WHERE id=?", (now,row['id']))
    status = 'sent'
    due = now
    try:
        # A durable link carries no login bearer token. It opens only the currently
        # authenticated pupil's work; /my provides a fresh personal login on demand.
        client.send(int(row['user_id'][4:]), 'Учитель вернул работу на исправление. Комментарий и повторная отправка доступны в кабинете ученика.',
                    buttons=[[{'type':'link','text':'Открыть работу','url':app_origin()+'/?open=student:'+valid['assignment_id']}],
                             [{'type':'message','text':'Мои работы'}]])
    except APIError as exc:
        if exc.status == 429 and row['tries'] < 4:
            status = 'queued'; due = now + min(3600, 30 * 2**row['tries'])
        else:
            status = 'unavailable' if 400 <= exc.status < 500 else 'unknown'
    except Exception:
        # A timeout or 5xx can follow a successful send. Prevent duplicate pushes.
        status = 'unknown'
    with connection() as conn:
        conn.execute('UPDATE student_notifications SET status=?,due_at=?,updated_at=? WHERE id=? AND status=\'sending\'',
                     (status,due,time.time(),row['id']))
    return True
