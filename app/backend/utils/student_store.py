"""Invited pupils, private submissions and versioned corrections.

The short printed pupil code is an identifier, never a login credential.
Official grades change only in the teacher's confirmation transaction.
"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import time
import uuid

from utils import class_store, db, review_store
from utils.answer_check import hint
from utils.gigachat_client import AIServiceError
from utils.workspace_store import connection, timestamp

RETENTION = 7 * 86400


def fail(message, code='student_invalid', status=400):
    raise AIServiceError(message, code, status)


def folder(attempt_id):
    if not re.fullmatch(r'[a-f0-9]{32}', attempt_id):
        fail('Работа не найдена.', 'student_not_found', 404)
    root = Path(db.DB_PATH).resolve().parent / 'student_uploads'
    root.mkdir(exist_ok=True)
    return root / attempt_id


def linked(conn, user, assignment_id, active=False):
    row = conn.execute('''SELECT a.*,l.student_id,s.archived AS pupil_archived,c.archived AS class_archived
        FROM student_links l JOIN students s ON s.id=l.student_id JOIN classrooms c ON c.id=s.class_id
        JOIN assignment_students r ON r.student_id=s.id JOIN assignments a ON a.id=r.assignment_id
        WHERE l.user_id=? AND a.id=?''', (user, assignment_id)).fetchone()
    if row is None:
        fail('Работа не найдена в вашем кабинете.', 'student_not_found', 404)
    if active and (row['status'] != 'active' or row['pupil_archived'] or row['class_archived']):
        fail('Приём работ закрыт. Обратитесь к учителю.', 'student_closed', 409)
    return row


def teacher_pupil(conn, owner, student_id):
    row = conn.execute('SELECT s.*,c.owner_id,c.archived AS class_archived FROM students s JOIN classrooms c ON c.id=s.class_id WHERE s.id=? AND c.owner_id=?', (student_id, owner)).fetchone()
    if row is None:
        fail('Ученик не найден.', 'student_not_found', 404)
    if row['archived'] or row['class_archived']:
        fail('Сначала верните ученика и класс из архива.', 'student_closed', 409)
    return row


def invite(owner, student_id):
    token = secrets.token_urlsafe(24)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        teacher_pupil(conn, owner, student_id)
        if conn.execute('SELECT 1 FROM student_links WHERE student_id=?', (student_id,)).fetchone():
            fail('Ученик уже подключён. Сначала отзовите доступ, если нужно заменить аккаунт.', 'student_connected', 409)
        conn.execute('DELETE FROM student_invites WHERE student_id=?', (student_id,))
        conn.execute('INSERT INTO student_invites VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), student_id, owner, time.time()+86400))
    return {'token': token, 'student_code': class_store.student_code(student_id), 'expires_in': 86400}


def revoke(owner, student_id):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        teacher_pupil(conn, owner, student_id)
        conn.execute('DELETE FROM student_links WHERE student_id=?', (student_id,))
        conn.execute('DELETE FROM student_invites WHERE student_id=?', (student_id,))


def claim(user, value):
    token = value.get('token')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', token):
        fail('Проверьте приглашение учителя.', 'student_invite_invalid', 404)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        invitation = conn.execute('SELECT * FROM student_invites WHERE token_hash=? AND expires_at>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if invitation is None:
            fail('Приглашение использовано или истекло. Попросите учителя создать новое.', 'student_invite_invalid', 404)
        pupil = teacher_pupil(conn, invitation['owner_id'], invitation['student_id'])
        # Demo and real identities cannot be linked to one another.
        from utils.demo_space import same_realm
        if user == invitation['owner_id'] or not same_realm(user,invitation['owner_id']):
            fail('Приглашение должен открыть ученик из своего кабинета MAX.', 'student_invite_identity', 409)
        if conn.execute('SELECT 1 FROM student_links l JOIN students s ON s.id=l.student_id WHERE l.user_id=? AND s.class_id=?', (user, pupil['class_id'])).fetchone():
            fail('Этот аккаунт уже подключён к ученику в данном классе.', 'student_connected', 409)
        if conn.execute('SELECT 1 FROM student_links WHERE student_id=?', (pupil['id'],)).fetchone():
            fail('Ученик уже подключён.', 'student_connected', 409)
        conn.execute('INSERT INTO student_links VALUES(?,?,?)', (pupil['id'], user, timestamp()))
        conn.execute('DELETE FROM student_invites WHERE student_id=?', (pupil['id'],))
    return {'student_code': class_store.student_code(pupil['id'])}


def owned_attempt(conn, owner, attempt_id):
    row = conn.execute('SELECT * FROM student_attempts WHERE id=? AND owner_id=?', (attempt_id, owner)).fetchone()
    if row is None:
        fail('Работа не найдена.', 'student_not_found', 404)
    return row


def can_read(conn, user, attempt_id):
    row = conn.execute('SELECT * FROM student_attempts WHERE id=?', (attempt_id,)).fetchone()
    if row is None:
        fail('Работа не найдена.', 'student_not_found', 404)
    if row['owner_id'] != user:
        assignment = linked(conn, user, row['assignment_id'])
        if row['user_id'] != user or assignment['student_id'] != row['student_id']:
            fail('Работа не найдена.', 'student_not_found', 404)
    return row


def attempt_view(conn, row, teacher=False):
    result = {k: row[k] for k in ('id', 'assignment_id', 'student_id', 'number', 'status', 'revision', 'feedback', 'created_at', 'updated_at', 'expires_at')}
    result['student_code'] = class_store.student_code(row['student_id'])
    files = json.loads(row['files']) if row['expires_at'] > time.time() else []
    result['files'] = [{'url':f"/api/v2/student-attempts/{row['id']}/files/{i}", 'name': ('Страница ' + str(i+1)) if name.endswith('.jpg') else 'PDF работы', 'image':name.endswith(('.jpg','.jpeg','.png'))} for i,name in enumerate(files)]
    if teacher:
        assignment = class_store.assignment_detail(conn, row['owner_id'], row['assignment_id'])
        result.update(title=assignment['title'], class_name=assignment['class_name'], tasks=assignment['worksheet']['tasks'],
                      answers=json.loads(row['answers']), warnings=json.loads(row['warnings']))
        if not result['answers']:
            result['answers'] = [{'task_id':t['id'], 'text':'', 'state':'unclear', 'score':None, 'comment':'', 'checked':False} for t in result['tasks']]
        job = conn.execute('SELECT status,error FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
        result['job_status'] = job['status'] if job else None
        result['error'] = job['error'] if job else None
        from utils.solution_store import latest
        result['solution_analysis']=latest(conn,row['owner_id'],'student',row['id'],row['revision'])
        official=conn.execute('SELECT id,revision,answers,status FROM reviews WHERE assignment_id=? AND student_id=?',(row['assignment_id'],row['student_id'])).fetchone()
        result['base_conflict']=row['status'] in ('submitted','needs_review') and ((official['id'] if official else None)!=row['review_id'] or (official['revision'] if official else None)!=row['base_revision'])
        result['current_review']={'id':official['id'],'revision':official['revision'],'score':sum(a['score'] for a in json.loads(official['answers'])) if official['status']=='confirmed' else None} if official else None
    return result


def overview(user):
    with connection() as conn:
        rows = conn.execute('''SELECT DISTINCT a.id FROM student_links l JOIN assignment_students r ON r.student_id=l.student_id
            JOIN assignments a ON a.id=r.assignment_id WHERE l.user_id=? ORDER BY a.created_at DESC''', (user,)).fetchall()
        return [student_assignment(conn, user, row['id'], False) for row in rows]


def student_assignment(conn, user, assignment_id, details=True):
    row = linked(conn, user, assignment_id)
    assignment = class_store.assignment_detail(conn, row['owner_id'], assignment_id)
    result = {k:assignment[k] for k in ('id','title','class_name','due_date','scheduled_date','instructions','status','topic','code')}
    result.update(student_code=class_store.student_code(row['student_id']), accepting=row['status']=='active' and not row['pupil_archived'] and not row['class_archived'])
    result['pdf_url'] = f'/api/v2/student/assignments/{assignment_id}/worksheet.pdf'
    attempts = conn.execute('SELECT * FROM student_attempts WHERE assignment_id=? AND student_id=? AND user_id=? ORDER BY number DESC', (assignment_id, row['student_id'], user)).fetchall()
    result['attempts'] = [attempt_view(conn, a) for a in attempts]
    last = conn.execute('SELECT status FROM student_attempts WHERE assignment_id=? AND student_id=? ORDER BY number DESC LIMIT 1', (assignment_id,row['student_id'])).fetchone()
    grade = conn.execute("SELECT * FROM reviews WHERE assignment_id=? AND student_id=? AND status='confirmed'", (assignment_id,row['student_id'])).fetchone()
    result['can_submit'] = result['accepting'] and (last['status']=='returned' if last else not bool(grade))
    result['result'] = None
    if grade:
        answers=json.loads(grade['answers'])
        result['result']={'score':sum(a['score'] for a in answers), 'max_score':len(answers), 'comment':grade['comment'], 'confirmed_at':grade['confirmed_at'],
                          'answers':[{k:a.get(k) for k in ('task_id','text','score','comment')} for a in answers]}
    if details:
        # No answer keys, solutions, teacher notes, roster or material identifiers.
        result['tasks']=[{'id':t['id'],'question':t['question']} for t in assignment['worksheet']['tasks']]
    return result


def upload(user, assignment_id, key, paths):
    from utils.job_store import validate_key, fingerprint
    validate_key(key)
    signature=fingerprint('student_submission', {'assignment_id':assignment_id}, paths)
    attempt_id=uuid.uuid4().hex
    destination=folder(attempt_id)
    try:
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            assignment=linked(conn,user,assignment_id,True)
            old=conn.execute('SELECT * FROM student_attempts WHERE user_id=? AND request_key=?',(user,key)).fetchone()
            if old:
                if old['fingerprint']!=signature:fail('Этот запрос уже использован для другого файла.','request_key_conflict',409)
                return attempt_view(conn,old),False
            last=conn.execute('SELECT * FROM student_attempts WHERE assignment_id=? AND student_id=? ORDER BY number DESC LIMIT 1',(assignment_id,assignment['student_id'])).fetchone()
            grade=conn.execute('SELECT id,revision,status FROM reviews WHERE assignment_id=? AND student_id=?',(assignment_id,assignment['student_id'])).fetchone()
            if (last and last['status']!='returned') or (not last and grade):
                fail('Работа уже отправлена. Новую попытку можно загрузить после возврата учителем.','student_attempt_pending',409)
            if last and last['number']>=10:fail('Достигнут предел: 10 попыток. Обратитесь к учителю.','student_attempt_limit',409)
            destination.mkdir()
            names=[]
            for i,path in enumerate(paths):
                name=str(i)+Path(path).suffix.lower()
                shutil.copyfile(path,destination/name);names.append(name)
            now=timestamp()
            conn.execute('''INSERT INTO student_attempts(id,owner_id,user_id,assignment_id,student_id,number,request_key,fingerprint,files,expires_at,review_id,base_revision,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (attempt_id,assignment['owner_id'],user,assignment_id,assignment['student_id'],last['number']+1 if last else 1,key,signature,json.dumps(names),time.time()+RETENTION,grade['id'] if grade else None,grade['revision'] if grade else None,now,now))
            return attempt_view(conn,owned_attempt(conn,assignment['owner_id'],attempt_id)),True
    except BaseException:
        if destination.exists():shutil.rmtree(destination)
        raise


def inbox(owner):
    with connection() as conn:
        return [attempt_view(conn,row,True) for row in conn.execute('SELECT * FROM student_attempts WHERE owner_id=? ORDER BY created_at DESC LIMIT 300',(owner,))]


def enqueue(conn, owner, attempt_id, job_id, expected_revision):
    row=owned_attempt(conn,owner,attempt_id)
    if row['revision']!=expected_revision or row['status'] not in ('submitted','needs_review'):
        fail('Работа изменилась. Обновите список.','revision_conflict',409)
    if row['expires_at']<=time.time():fail('Срок хранения сканов истёк. Верните работу ученику для повторной загрузки.','student_files_expired',409)
    assignment=review_store.context(conn,owner,row['assignment_id'],row['student_id'])
    conn.execute("UPDATE student_attempts SET job_id=?,status='processing',revision=revision+1,updated_at=? WHERE id=?",(job_id,timestamp(),attempt_id))
    return assignment


def complete(conn, owner, attempt_id, job_id, output, paths):
    row=owned_attempt(conn,owner,attempt_id)
    if row['status']!='processing' or row['job_id']!=job_id:
        fail('Проверка уже изменена.','revision_conflict',409)
    assignment=review_store.context(conn,owner,row['assignment_id'],row['student_id'])
    tasks=assignment['worksheet']['tasks']
    answers=review_store.validate_recognition(output,tasks)
    warnings=[]
    for answer,task in zip(answers,tasks):
        answer.update(hint(task['answer'],answer['text'],answer['state']))
        answer.update(score=answer['suggested_score'],comment='',checked=False)
    for page in output.get('page_codes',[output]):
        for field,expected in [('student_code',class_store.student_code(row['student_id'])),('edition_code',assignment['code']),('assignment_code',assignment['id'])]:
            actual=str(page.get(field,''))[:80]
            if actual and actual.upper().replace(' ','')!=expected.upper():warnings.append('На скане другой код. Сверьте работу: '+actual)
    conflicts=set(output.get('conflict_task_ids',[]))
    for answer in answers:
        if answer['task_id'] in conflicts:
            answer.update(state='unclear',score=None,suggested_score=None,checked=False)
    if conflicts:warnings.append('На разных страницах отличаются ответы. Требуется сверка.')
    files=[n for n in json.loads(row['files']) if not n.startswith('page_')]
    for i,path in enumerate(paths):
        name=f'page_{i+1}.jpg';shutil.copyfile(path,folder(attempt_id)/name);files.append(name)
    conn.execute("UPDATE student_attempts SET status='needs_review',answers=?,warnings=?,files=?,revision=revision+1,updated_at=? WHERE id=?",(json.dumps(answers,ensure_ascii=False),json.dumps(warnings,ensure_ascii=False),json.dumps(files),timestamp(),attempt_id))
    return {'student_attempt_id':attempt_id,'assignment_id':row['assignment_id']}


def update(owner, attempt_id, value):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=owned_attempt(conn,owner,attempt_id)
        if type(value.get('revision')) is not int or row['revision']!=value['revision']:
            fail('Работа изменилась на другом устройстве. Обновите её.','revision_conflict',409)
        if row['status']=='processing':fail('Дождитесь завершения распознавания.','student_processing',409)
        action=value.get('action')
        if action=='return':
            feedback=value.get('feedback','')
            if not isinstance(feedback,str) or not 1<=len(feedback.strip())<=2000:fail('Напишите, что нужно исправить: до 2000 символов.')
            latest=conn.execute('SELECT id FROM student_attempts WHERE assignment_id=? AND student_id=? ORDER BY number DESC LIMIT 1',(row['assignment_id'],row['student_id'])).fetchone()
            if latest['id']!=attempt_id or row['status']=='returned':fail('Откройте последнюю попытку.','revision_conflict',409)
            conn.execute("UPDATE student_attempts SET status='returned',feedback=?,revision=revision+1,updated_at=? WHERE id=?",(feedback.strip(),timestamp(),attempt_id))
        elif action=='confirm':
            if value.get('reviewed') is not True:fail('Подтвердите, что сверили сканы и баллы.','review_required')
            if row['status'] not in ('submitted','needs_review'):fail('Эту попытку уже завершили.','revision_conflict',409)
            existing=conn.execute('SELECT * FROM reviews WHERE assignment_id=? AND student_id=?',(row['assignment_id'],row['student_id'])).fetchone()
            if (existing['id'] if existing else None)!=row['review_id'] or (existing['revision'] if existing else None)!=row['base_revision']:
                accepted=value.get('replace_review')
                if not existing or not isinstance(accepted,dict) or accepted.get('id')!=existing['id'] or type(accepted.get('revision')) is not int or accepted['revision']!=existing['revision']:
                    fail('Результат изменён другим способом. Обновите страницу и сверьте текущую оценку.','review_base_conflict',409)
            if existing and conn.execute('SELECT 1 FROM review_drafts WHERE review_id=?',(existing['id'],)).fetchone():fail('Есть несохранённая проверка этой работы. Завершите её сначала.','draft_conflict',409)
            editable=dict(row)
            editable['answers']=json.dumps(attempt_view(conn,row,True)['answers'],ensure_ascii=False)
            payload=review_store.editable(conn,owner,editable,value,True)
            now=timestamp();review_id=existing['id'] if existing else uuid.uuid4().hex
            if not existing:
                conn.execute('''INSERT INTO reviews(id,owner_id,assignment_id,student_id,job_id,fingerprint,photo_expires,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)''',(review_id,owner,row['assignment_id'],row['student_id'],row['job_id'] or attempt_id,'student:'+attempt_id,row['expires_at'],now,now))
            images=[n for n in json.loads(row['files']) if n.startswith('page_') and n.endswith('.jpg')] if row['expires_at']>time.time() else []
            for i,name in enumerate(images):
                target=review_store.photo_path(review_id,i);target.parent.mkdir(exist_ok=True);shutil.copyfile(folder(attempt_id)/name,target)
            conn.execute("UPDATE reviews SET status='confirmed',answers=?,warnings=?,comment=?,revision=revision+1,photo_count=?,photo_expires=?,updated_at=?,confirmed_at=? WHERE id=?",(json.dumps(payload['answers'],ensure_ascii=False),row['warnings'],payload['comment'],len(images),row['expires_at'],now,now,review_id))
            review_store.audit(conn,review_store.owned(conn,owner,review_id),'student_confirm')
            conn.execute("UPDATE student_attempts SET status='confirmed',answers=?,feedback=?,review_id=?,revision=revision+1,updated_at=? WHERE id=?",(json.dumps(payload['answers'],ensure_ascii=False),payload['comment'],review_id,now,attempt_id))
        else:fail('Неизвестное действие.')
        return attempt_view(conn,owned_attempt(conn,owner,attempt_id),True)


def maintain(conn, now):
    conn.execute('DELETE FROM student_invites WHERE expires_at<?',(now,))
    conn.execute("UPDATE student_attempts SET status='submitted',revision=revision+1 WHERE status='processing' AND job_id IN (SELECT id FROM jobs WHERE status IN ('failed','cancelled'))")
    for row in conn.execute("SELECT id,files FROM student_attempts WHERE expires_at<? AND files!='[]' AND status!='processing'",(now,)).fetchall():
        for name in json.loads(row['files']):(folder(row['id'])/name).unlink(missing_ok=True)
        conn.execute("UPDATE student_attempts SET files='[]' WHERE id=?",(row['id'],))


def return_review(owner,review_id,value):
    feedback=value.get('feedback','')
    if not isinstance(feedback,str) or not 1<=len(feedback.strip())<=2000:fail('Напишите, что нужно исправить.')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        review=review_store.owned(conn,owner,review_id)
        if type(value.get('revision')) is not int or value['revision']!=review['revision'] or review['status']!='confirmed':
            fail('Обновите подтверждённую проверку.','revision_conflict',409)
        link=conn.execute('SELECT user_id FROM student_links WHERE student_id=?',(review['student_id'],)).fetchone()
        if not link:fail('Сначала пригласите ученика в кабинет через список класса.','student_not_connected',409)
        linked(conn,link['user_id'],review['assignment_id'],True)
        last=conn.execute('SELECT id,status FROM student_attempts WHERE assignment_id=? AND student_id=? ORDER BY number DESC LIMIT 1',(review['assignment_id'],review['student_id'])).fetchone()
        if last:
            fail('У ученика уже есть попытка. Откройте её в разделе «От учеников».','student_attempt_exists',409)
        aid=uuid.uuid4().hex;now=timestamp()
        conn.execute('''INSERT INTO student_attempts(id,owner_id,user_id,assignment_id,student_id,number,request_key,fingerprint,files,expires_at,status,feedback,review_id,base_revision,created_at,updated_at)
            VALUES(?,?,?,?,?,1,?,?,?,?,'returned',?,?,?,?,?)''',(aid,owner,link['user_id'],review['assignment_id'],review['student_id'],uuid.uuid4().hex,'return:'+review_id,'[]',time.time()+RETENTION,feedback.strip(),review_id,review['revision'],now,now))
        return attempt_view(conn,owned_attempt(conn,owner,aid),True)
