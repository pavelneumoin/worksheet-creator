from flask import Blueprint, g, jsonify, send_from_directory
from utils import demo_space
from utils.workspace_store import connection
from utils.sessions import session_json

api=Blueprint('demo_space',__name__,url_prefix='/api/v2/demo-space')

@api.post('/enter')
def enter():
    real=g.identity.get('real_owner_id',g.identity['owner_id'])
    owner=demo_space.ensure(real)
    with connection() as conn:
        conn.execute('INSERT OR REPLACE INTO demo_sessions VALUES(?,?)',(g.identity['token_hash'],owner))
        conn.execute('DELETE FROM download_tickets WHERE session_hash=?',(g.identity['token_hash'],))
    return jsonify(demo=True)

@api.post('/exit')
def leave():
    with connection() as conn:
        conn.execute('DELETE FROM demo_sessions WHERE session_hash=?',(g.identity['token_hash'],))
        conn.execute('DELETE FROM download_tickets WHERE session_hash=?',(g.identity['token_hash'],))
    return jsonify(demo=False)

@api.get('')
def details():
    return jsonify(demo=demo_space.manifest(g.identity['owner_id']))

@api.get('/files/<name>')
def file(name):
    from utils.workspace_store import missing
    if name not in ('fractions.png','equations.png','physics.png','roster.png'):
        missing()
    return send_from_directory(demo_space.ASSETS,name,as_attachment=True)
