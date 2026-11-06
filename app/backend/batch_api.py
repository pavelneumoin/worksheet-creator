from pathlib import Path
import tempfile
from flask import Blueprint,g,jsonify,request,send_file
from class_api import body
from utils import batch_review,class_store,job_store
from utils.workspace_store import connection
from utils.gigachat_client import AIServiceError,get_ai_status

api=Blueprint('batch_reviews',__name__,url_prefix='/api/v2')

@api.post('/jobs/batch_grade')
def submit():
    job_store.validate_key(request.headers.get('Idempotency-Key'))
    assignment_id=request.form.get('assignment_id','')
    with connection() as conn:class_store.assignment_detail(conn,g.identity['owner_id'],assignment_id)
    files=[f for f in request.files.getlist('files') if f.filename]
    if len(files)!=1:raise AIServiceError('Загрузите один PDF со сканами класса.','invalid_batch_file',400)
    file=files[0];head=file.stream.read(8);file.stream.seek(0,2);size=file.stream.tell();file.stream.seek(0)
    if Path(file.filename).suffix.lower()!='.pdf' or not head.startswith(b'%PDF-'):raise AIServiceError('Нужен PDF без пароля.','invalid_pdf',415)
    if size>15*1024*1024:raise AIServiceError('PDF должен быть не больше 15 МБ.','file_too_large',413)
    status=get_ai_status()
    if not status['ai_ready']:raise AIServiceError(status['ai_message'],'ai_not_configured',503)
    with tempfile.TemporaryDirectory(prefix='listok-batch-') as tmp:
        path=Path(tmp)/'scans.pdf';file.save(path)
        job,created=job_store.submit(g.identity['owner_id'],'batch_grade',request.headers['Idempotency-Key'],{'assignment_id':assignment_id},[path])
    return jsonify(job=job,reused=not created),202 if job['status'] in job_store.ACTIVE else 200

@api.get('/assignments/<assignment_id>/batches')
def listing(assignment_id):
    job_store.maintain()
    return jsonify(batches=batch_review.list_batches(g.identity['owner_id'],assignment_id))

@api.get('/batches/<batch_id>')
def detail(batch_id):
    job_store.maintain()
    return jsonify(batch=batch_review.get(g.identity['owner_id'],batch_id))

@api.post('/batches/<batch_id>/attach')
def attach(batch_id):return jsonify(batch_review.attach(g.identity['owner_id'],batch_id,body()))

@api.get('/batches/<batch_id>/photos/<int:index>')
def photo(batch_id,index):
    data=batch_review.get(g.identity['owner_id'],batch_id)
    if data['expired'] or not any(p['index']==index for p in data['pages']):raise AIServiceError('Скан недоступен.','batch_photo_not_found',404)
    path=batch_review.photo(batch_id,index)
    if not path.is_file():raise AIServiceError('Скан недоступен.','batch_photo_not_found',404)
    return send_file(path,mimetype='image/jpeg',conditional=False)
