"""Opaque revocable sessions. MAX identity is accepted only after signature validation."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, request

from utils.gigachat_client import AIServiceError
from utils.max_auth import validate_init_data
from utils.workspace_store import connection

auth = Blueprint('auth', __name__, url_prefix='/api/v2/auth')
COOKIE = 'listok_session'
TTL = 7 * 24 * 3600
PUBLIC_ENDPOINTS = {'index', 'static', 'status', 'demo', 'workspace.demo',
                    'auth.me', 'auth.login_max', 'auth.login_local', 'workspace.max_launch', 'workspace.download_file'}


def local_mode():
    return current_app.config['LISTOK_AUTH_MODE'] == 'local'


def local_allowed():
    return (local_mode() and request.remote_addr in ('127.0.0.1', '::1')
            and request.host.split(':')[0] in ('localhost', '127.0.0.1', '[::1]'))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def origin_check():
    origin = request.headers.get('Origin')
    configured = os.environ.get('MAX_APP_URL', '').strip()
    parts = urlsplit(configured)
    expected = request.host_url.rstrip('/') if local_mode() else f'{parts.scheme}://{parts.netloc}'
    if request.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and origin != expected):
        raise AIServiceError('Откройте приложение заново.', 'origin_rejected', 403)


def load_session():
    g.identity = None
    raw = request.cookies.get(COOKIE, '')
    if raw and len(raw) < 200:
        with connection() as conn:
            row = conn.execute('''SELECT sessions.*,users.first_name,users.kind FROM sessions
                                  JOIN users ON users.id=sessions.owner_id
                                  WHERE token_hash=? AND expires_at>?''', (token_hash(raw), int(time.time()))).fetchone()
            if row and (row['kind'] != 'local' or local_allowed()):
                g.identity = dict(row)
    # Unknown routes remain 404, without exposing any data.
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS or not request.path.startswith('/api/'):
        return
    if g.identity is None:
        raise AIServiceError('Откройте ЛистОК через своего бота в MAX.', 'login_required', 401)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin_check()
        csrf = request.headers.get('X-CSRF-Token', '')
        if not hmac.compare_digest(csrf, g.identity['csrf']):
            raise AIServiceError('Сессия обновилась. Перезагрузите приложение.', 'csrf_invalid', 403)


def session_json(identity):
    return {'authenticated': True, 'user': {'first_name': identity['first_name'], 'kind': identity['kind']},
            'csrf_token': identity['csrf']}


def issue_session(owner, name, kind):
    raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = int(time.time())
    with connection() as conn:
        conn.execute('DELETE FROM sessions WHERE expires_at<=?', (now,))
        conn.execute('INSERT INTO users VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET first_name=excluded.first_name', (owner, name, kind))
        old = request.cookies.get(COOKIE, '')
        if old:
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(old),))
        conn.execute('INSERT INTO sessions VALUES (?,?,?,?)', (token_hash(raw), owner, csrf, now + TTL))
    response = jsonify(session_json({'first_name': name, 'kind': kind, 'csrf': csrf}))
    response.set_cookie(COOKIE, raw, max_age=TTL, httponly=True, secure=not local_mode(),
                        samesite='Lax' if local_mode() else 'None', path='/')
    return response


@auth.get('/me')
def me():
    if g.identity:
        return jsonify(session_json(g.identity))
    username = os.environ.get('MAX_BOT_USERNAME', '').lstrip('@')
    return jsonify(authenticated=False, local_available=local_allowed(),
                   max_url=f'https://max.ru/{username}?startapp' if username and username.replace('_', '').isalnum() else None)


@auth.post('/max')
def login_max():
    origin_check()
    token = os.environ.get('MAX_BOT_TOKEN', '').strip()
    if not token:
        raise AIServiceError('Бот MAX пока не подключён.', 'max_not_configured', 503)
    data = request.get_json(silent=True)
    user = validate_init_data(data.get('init_data') if isinstance(data, dict) else None, token)
    return issue_session(f"max:{user['id']}", user['first_name'], 'max')


@auth.post('/local')
def login_local():
    if not local_allowed():
        raise AIServiceError('Локальный вход недоступен.', 'local_login_disabled', 403)
    origin_check()
    # Identity cannot be supplied by a browser. Each local browser gets a separate account.
    if g.identity:
        return jsonify(session_json(g.identity))
    return issue_session('local:' + secrets.token_hex(16), 'Локальный профиль', 'local')


@auth.post('/logout')
def logout():
    with connection() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash=?', (g.identity['token_hash'],))
    response = jsonify(authenticated=False)
    response.delete_cookie(COOKIE, path='/', secure=not local_mode(), samesite='Lax' if local_mode() else 'None')
    return response


def init_auth(app):
    app.config['LISTOK_AUTH_MODE'] = os.environ.get('LISTOK_AUTH_MODE', 'max')
    if app.config['LISTOK_AUTH_MODE'] not in ('max', 'local'):
        raise RuntimeError('LISTOK_AUTH_MODE must be max or local')
    app.register_blueprint(auth)
    app.before_request(load_session)
