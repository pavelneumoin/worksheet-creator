"""Short-lived login links issued only for authenticated private MAX events."""
import hashlib
import os
import re
import secrets
import time

from utils.gigachat_client import AIServiceError
from utils.workspace_store import connection

LOGIN_TTL = 300


def enabled():
    return os.environ.get('LISTOK_BOT_LOGIN_ENABLED') == '1'


def digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue(user_id, first_name, now=None):
    if type(user_id) is not int or user_id <= 0:
        raise ValueError('Invalid MAX identity')
    now = int(time.time() if now is None else now)
    raw = secrets.token_urlsafe(32)
    with connection() as conn:
        conn.execute('DELETE FROM bot_login_tokens WHERE expires_at<=?', (now,))
        # A fresh /start replaces any unused links for this account.
        conn.execute('DELETE FROM bot_login_tokens WHERE owner_id=?', (f'max:{user_id}',))
        conn.execute('INSERT INTO bot_login_tokens VALUES (?,?,?,?)',
                     (digest(raw), f'max:{user_id}', str(first_name)[:100], now + LOGIN_TTL))
    return raw


def lookup(raw, *, consume=False, now=None):
    def reject():
        raise AIServiceError('Ссылка уже использована или устарела. Отправьте боту /start для нового входа.',
                             'bot_login_invalid', 401)
    if not enabled() or not isinstance(raw, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', raw):
        reject()
    now = int(time.time() if now is None else now)
    with connection() as conn:
        if consume:
            # DELETE RETURNING is atomic: two devices cannot redeem the same link.
            row = conn.execute('DELETE FROM bot_login_tokens WHERE token_hash=? AND expires_at>? RETURNING *',
                               (digest(raw), now)).fetchone()
        else:
            row = conn.execute('SELECT * FROM bot_login_tokens WHERE token_hash=? AND expires_at>?',
                               (digest(raw), now)).fetchone()
        result = dict(row) if row else None
    if result is None:
        reject()
    return result


def event_request(update, now=None):
    """Discard group traffic, bot messages and all content except explicit commands."""
    if not isinstance(update, dict):
        return None
    now = time.time() if now is None else now
    stamp = update.get('timestamp')
    if type(stamp) is not int or not -60 <= now - stamp / 1000 <= 600:
        return None
    kind = update.get('update_type')
    if kind == 'bot_started':
        user = update.get('user')
        source = f'start:{stamp}'
        action = 'login'
    elif kind == 'message_created':
        message = update.get('message')
        if not isinstance(message, dict) or not isinstance(message.get('recipient'), dict):
            return None
        if message['recipient'].get('chat_type') != 'dialog':
            return None
        user = message.get('sender')
        body = message.get('body')
        if not isinstance(body, dict) or not isinstance(body.get('text'), str):
            return None
        command = body['text'].strip().lower()
        if command not in ('/start', '/login', '/help', 'начать', 'войти'):
            return None
        action = 'help' if command == '/help' else 'login'
        mid = body.get('mid')
        if not isinstance(mid, str) or not 1 <= len(mid) <= 200:
            return None
        source = 'message:' + mid
    else:
        return None
    if (not isinstance(user, dict) or type(user.get('user_id')) is not int
            or user['user_id'] <= 0 or user.get('is_bot') is not False):
        return None
    return {'id': digest(f"{user['user_id']}:{source}"), 'user_id': user['user_id'],
            'first_name': str(user.get('first_name') or 'Учитель')[:100], 'action': action}


def enqueue(update):
    now = time.time()
    item = event_request(update, now)
    if item is None:
        return
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM bot_inbox WHERE created_at<?', (now - 86400,))
        # Protect a double tap and duplicate deliveries without a second response.
        recent = conn.execute('SELECT 1 FROM bot_inbox WHERE user_id=? AND created_at>?',
                              (item['user_id'], now - 5)).fetchone()
        if not recent:
            conn.execute('INSERT OR IGNORE INTO bot_inbox(id,user_id,first_name,action,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                         (item['id'], item['user_id'], item['first_name'], item['action'], now, now))


def claim():
    now = time.time()
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Do not replay an ambiguous outbound send after a crash. /start can be retried.
        conn.execute("UPDATE bot_inbox SET status='failed' WHERE status='sending' AND updated_at<?", (now - 60,))
        conn.execute("UPDATE bot_inbox SET status='expired' WHERE status='queued' AND created_at<?", (now - 300,))
        row = conn.execute("SELECT * FROM bot_inbox WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if row:
            conn.execute("UPDATE bot_inbox SET status='sending',updated_at=? WHERE id=?", (now, row['id']))
            return dict(row)
    return None


def finish(event_id, success):
    with connection() as conn:
        conn.execute('UPDATE bot_inbox SET status=?,updated_at=? WHERE id=?',
                     ('sent' if success else 'failed', time.time(), event_id))
