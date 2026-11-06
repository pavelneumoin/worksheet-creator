"""Authenticated student portal and teacher submission inbox."""
import json
from pathlib import Path
import tempfile
import time
from flask import Blueprint, g, jsonify, request, send_file
from class_api import body
from utils import job_store, latex, student_store
from utils.gigachat_client import AIServiceError, get_ai_status
from utils.workspace_store import connection

api=Blueprint('students',__name__,url_prefix='/api/v2')

@api.post('/students/<student_id>/invite')
def invite(student_id):
    return jsonify(invitation=student_store.invite(g.identity['owner_id'],student_id)),201

@api.delete('/students/<student_id>/access')
def revoke(student_id):
    student_store.revoke(g.identity['owner_id'],student_id)
    return jsonify(revoked=True)

@api.post('/student/join')
def join():
    return jsonify(**student_store.claim(g.identity['owner_id'],body()))

@api.get('/student/assignments')
def assignments():
    job_store.maintain()
    return jsonify(assignments=student_store.overview(g.identity['owner_id']))

@api.get('/student/assignments/<assignment_id>')
def assignment(assignment_id):
    with connection() as conn:
        return jsonify(assignment=student_store.student_assignment(conn,g.identity['owner_id'],assignment_id))

@api.get('/student/assignments/<assignment_id>/worksheet.pdf')
def worksheet(assignment_id):
    with connection() as conn:
        student_store.linked(conn,g.identity['owner_id'],assignment_id)
        row=conn.execute('SELECT f.pdf FROM assignments a JOIN artifacts f ON f.id=a.edition_id WHERE a.id=?',(assignment_id,)).fetchone()
    path=Path(latex.OUTPUT_DIR)/row['pdf']
    if not path.is_file():raise AIServiceError('Файл пока недоступен. Сообщите учителю.','file_not_found',404)
    return send_file(path,mimetype='application/pdf',download_name='worksheet.pdf',conditional=False)

@api.post('/student/assignments/<assignment_id>/attempts')
def upload(assignment_id):
    key=job_store.validate_key(request.headers.get('Idempotency-Key'))
    with connection() as conn:student_store.linked(conn,g.identity['owner_id'],assignment_id,True)
    files=[f for f in request.files.getlist('files') if f.filename]
    if not 1<=len(files)<=10:raise AIServiceError('Выберите один PDF или до 10 фотографий.','input_limit',400)
    suffixes=[Path(f.filename).suffix.lower() for f in files]
    if '.pdf' in suffixes and len(files)!=1:raise AIServiceError('Загрузите один PDF или фотографии отдельно.','input_limit',400)
    with tempfile.TemporaryDirectory(prefix='listok-student-') as directory:
        paths=[]
        for i,file in enumerate(files):
            ext=suffixes[i];head=file.stream.read(8);file.stream.seek(0,2);size=file.stream.tell();file.stream.seek(0)
            if size>15*1024*1024:raise AIServiceError('Файл должен быть не больше 15 МБ.','file_too_large',413)
            if not ((ext=='.pdf' and head.startswith(b'%PDF-')) or (ext=='.png' and head.startswith(b'\x89PNG\r\n\x1a\n')) or (ext in ('.jpg','.jpeg') and head.startswith(b'\xff\xd8\xff'))):
                raise AIServiceError('Поддерживаются PDF, JPEG и PNG.','invalid_file',415)
            path=Path(directory)/(str(i)+ext);file.save(path);paths.append(path)
        result,created=student_store.upload(g.identity['owner_id'],assignment_id,key,paths)
    return jsonify(attempt=result),201 if created else 200

@api.get('/student-attempts')
def inbox():
    job_store.maintain()
    return jsonify(attempts=student_store.inbox(g.identity['owner_id']))

@api.get('/student-attempts/<attempt_id>')
def detail(attempt_id):
    with connection() as conn:
        row=student_store.can_read(conn,g.identity['owner_id'],attempt_id)
        return jsonify(attempt=student_store.attempt_view(conn,row,row['owner_id']==g.identity['owner_id']))

@api.get('/student-attempts/<attempt_id>/files/<int:index>')
def file(attempt_id,index):
    with connection() as conn:row=student_store.can_read(conn,g.identity['owner_id'],attempt_id)
    files=json.loads(row['files'])
    if row['expires_at']<=time.time() or not 0<=index<len(files):raise AIServiceError('Срок хранения скана истёк.','file_not_found',404)
    path=student_store.folder(attempt_id)/files[index]
    if path.is_symlink() or not path.is_file():raise AIServiceError('Файл не найден.','file_not_found',404)
    return send_file(path,conditional=False)

@api.post('/student-attempts/<attempt_id>/recognize')
def recognize(attempt_id):
    value=body();status=get_ai_status()
    if not status['ai_ready']:raise AIServiceError(status['ai_message'],'ai_not_configured',503)
    with connection() as conn:
        row=student_store.owned_attempt(conn,g.identity['owner_id'],attempt_id)
        names=[n for n in json.loads(row['files']) if not n.startswith('page_')]
        if row['expires_at']<=time.time() or not names:raise AIServiceError('Срок хранения сканов истёк.','file_not_found',404)
    job,_=job_store.submit(g.identity['owner_id'],'student_grade',request.headers.get('Idempotency-Key'),
        {'attempt_id':attempt_id,'revision':value.get('revision')},[student_store.folder(attempt_id)/n for n in names])
    return jsonify(job=job),202

@api.put('/student-attempts/<attempt_id>')
def update(attempt_id):
    return jsonify(attempt=student_store.update(g.identity['owner_id'],attempt_id,body()))

@api.route('/student-attempts/<attempt_id>/draft', methods=['PUT','DELETE'])
def draft(attempt_id):
    from utils import student_drafts
    if request.method == 'DELETE':
        student_drafts.discard(g.identity['owner_id'], attempt_id, body())
        return jsonify(ok=True)
    return jsonify(draft=student_drafts.save(g.identity['owner_id'], attempt_id, body()))

@api.post('/reviews/<review_id>/return-to-student')
def return_review(review_id):
    return jsonify(attempt=student_store.return_review(g.identity['owner_id'],review_id,body()))
