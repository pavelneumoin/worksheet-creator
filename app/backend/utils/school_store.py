"""School membership is explicit; only its creator can administer that school."""
import hashlib
import secrets
import time
import uuid
from utils.workspace_store import connection,timestamp
from utils.class_store import label,fail

def membership(conn,user):
    return conn.execute('SELECT m.*,s.name,s.owner_id FROM school_members m JOIN schools s ON s.id=m.school_id WHERE m.user_id=?',(user,)).fetchone()

def require_admin(conn,user,school_id=None):
    m=membership(conn,user)
    if not m or m['role']!='admin' or m['owner_id']!=user or (school_id and m['school_id']!=school_id):fail('Нет доступа к управлению этой школой.','school_forbidden',403)
    return m

def current(user):
    with connection() as conn:
        m=membership(conn,user)
        if not m:return None
        result={k:m[k] for k in ('school_id','name','role')}
        if m['role']=='admin':
            result['members']=[dict(r) for r in conn.execute('SELECT m.user_id,m.role,m.joined_at,u.first_name FROM school_members m JOIN users u ON u.id=m.user_id WHERE m.school_id=? ORDER BY m.role,m.joined_at',(m['school_id'],))]
        return result

def create(user,value):
    name=label(value.get('name'),'Название школы',120)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if membership(conn,user):fail('Ваш профиль уже связан со школой.','school_exists',409)
        ident=uuid.uuid4().hex;now=timestamp()
        conn.execute('INSERT INTO schools VALUES(?,?,?,?)',(ident,name,user,now))
        conn.execute('INSERT INTO school_members VALUES(?,?,?,?)',(ident,user,'admin',now))
    return current(user)

def invite(user):
    token=secrets.token_urlsafe(24);expires=time.time()+7*86400
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE');m=require_admin(conn,user)
        conn.execute('DELETE FROM school_invites WHERE expires_at<?',(time.time(),))
        if conn.execute('SELECT COUNT(*) FROM school_invites WHERE school_id=?',(m['school_id'],)).fetchone()[0]>=30:fail('Для школы уже создано 30 действующих приглашений.','invite_limit',409)
        conn.execute('INSERT INTO school_invites VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),m['school_id'],expires))
    return {'code':token,'expires_at':expires}

def join(user,value):
    code=value.get('code')
    if value.get('share_statistics') is not True or not isinstance(code,str) or not 20<=len(code.strip())<=80:fail('Укажите приглашение и подтвердите доступ завуча к статистике ваших классов.','invalid_invite',400)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if membership(conn,user):fail('Ваш профиль уже связан со школой.','school_exists',409)
        digest=hashlib.sha256(code.strip().encode()).hexdigest()
        invite=conn.execute('SELECT * FROM school_invites WHERE token_hash=? AND expires_at>?',(digest,time.time())).fetchone()
        if not invite:fail('Приглашение недействительно или уже использовано.','invalid_invite',400)
        if conn.execute('SELECT COUNT(*) FROM school_members WHERE school_id=?',(invite['school_id'],)).fetchone()[0]>=100:fail('В школе уже 100 участников.','school_limit',409)
        conn.execute('INSERT INTO school_members VALUES(?,?,?,?)',(invite['school_id'],user,'teacher',timestamp()))
        conn.execute('DELETE FROM school_invites WHERE token_hash=?',(digest,))
    return current(user)

def leave(user,teacher=None):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE');m=membership(conn,user)
        if not m:fail('Школа не найдена.','school_not_found',404)
        target=teacher or user
        if teacher:require_admin(conn,user)
        if target==m['owner_id']:fail('Создатель школы сохраняет роль администратора.','school_owner',409)
        if not conn.execute('DELETE FROM school_members WHERE school_id=? AND user_id=?',(m['school_id'],target)).rowcount:fail('Участник не найден.','school_member_not_found',404)
