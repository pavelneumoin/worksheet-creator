"""Private photo reviews, explicit teacher confirmation and confirmed-only reports."""
from pathlib import Path
import tempfile
import uuid

from flask import Blueprint, Response, g, jsonify, request, send_file

from class_api import body
from utils import job_store, review_store, class_report, report_export
from utils.gigachat_client import AIServiceError, get_ai_status
from utils.workspace_store import connection

api = Blueprint('reviews', __name__, url_prefix='/api/v2')


@api.post('/assignments/<assignment_id>/submissions')
def submit(assignment_id):
    job_store.validate_key(request.headers.get('Idempotency-Key'))
    student_id = request.form.get('student_id', '')
    # Check access before accepting files or calling any provider.
    with connection() as conn:
        review_store.context(conn, g.identity['owner_id'], assignment_id, student_id)
    files = [f for f in request.files.getlist('files') if f.filename]
    if not 1 <= len(files) <= 5:
        raise AIServiceError('Добавьте от 1 до 5 фото ответов одного ученика.', 'input_limit', 400)
    status = get_ai_status()
    if not status['ai_ready']:
        raise AIServiceError(status['ai_message'], 'ai_not_configured', 503)
    with tempfile.TemporaryDirectory(prefix='listok-answers-') as temporary:
        paths = []
        for file in files:
            ext = Path(file.filename).suffix.lower()
            head = file.stream.read(8)
            file.stream.seek(0, 2)
            size = file.stream.tell()
            file.stream.seek(0)
            if size > 15 * 1024 * 1024:
                raise AIServiceError('Одно фото должно быть не больше 15 МБ.', 'file_too_large', 413)
            if not ((ext == '.png' and head.startswith(b'\x89PNG\r\n\x1a\n')) or
                    (ext in ('.jpg', '.jpeg') and head.startswith(b'\xff\xd8\xff'))):
                raise AIServiceError('Для проверки ответов нужны фотографии PNG или JPEG.', 'invalid_image', 415)
            target = Path(temporary) / (uuid.uuid4().hex + ext)
            file.save(target)
            paths.append(target)
        job, created = job_store.submit(g.identity['owner_id'], 'grade', request.headers['Idempotency-Key'],
                                       {'assignment_id': assignment_id, 'student_id': student_id}, paths)
    return jsonify(job=job, review_id=job['id'], reused=not created), 202 if job['status'] in job_store.ACTIVE else 200


@api.get('/reviews/<review_id>')
def detail(review_id):
    job_store.maintain()
    return jsonify(review=review_store.get_review(g.identity['owner_id'], review_id))


@api.put('/reviews/<review_id>')
def update(review_id):
    return jsonify(review=review_store.update(g.identity['owner_id'], review_id, body()))


@api.delete('/reviews/<review_id>')
def remove(review_id):
    value = body()
    review_store.remove(g.identity['owner_id'], review_id, value.get('revision'), value.get('draft_revision'))
    return jsonify(deleted=True)


@api.put('/reviews/<review_id>/draft')
def save_draft(review_id):
    return jsonify(draft=review_store.save_draft(g.identity['owner_id'], review_id, body()))


@api.delete('/reviews/<review_id>/draft')
def discard_draft(review_id):
    review_store.discard_draft(g.identity['owner_id'], review_id, body())
    return jsonify(deleted=True)


@api.get('/reviews/<review_id>/history')
def history(review_id):
    return jsonify(history=review_store.history(g.identity['owner_id'], review_id))


@api.get('/reviews/<review_id>/photos/<int:index>')
def photo(review_id, index):
    data = review_store.get_review(g.identity['owner_id'], review_id)
    if index >= len(data['photos']):
        raise AIServiceError('Фото удалено по сроку хранения или ещё обрабатывается.', 'photo_not_found', 404)
    path = review_store.photo_path(review_id, index)
    if not path.is_file():
        raise AIServiceError('Фото не найдено.', 'photo_not_found', 404)
    return send_file(path, mimetype='image/jpeg', conditional=False)


@api.get('/assignments/<assignment_id>/report')
def report(assignment_id):
    job_store.maintain()
    return jsonify(report=review_store.report(g.identity['owner_id'], assignment_id))


@api.get('/classes/<class_id>/report')
def overview(class_id):
    job_store.maintain()
    return jsonify(report=class_report.overview(g.identity['owner_id'], class_id, request.args))


@api.get('/assignments/<assignment_id>/report.csv')
def export(assignment_id):
    return Response(review_store.csv_report(g.identity['owner_id'], assignment_id), content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="class-report.csv"'})


@api.get('/classes/<class_id>/report.csv')
def overview_csv(class_id):
    data = class_report.overview(g.identity['owner_id'], class_id, request.args)
    return Response(report_export.overview_csv(data), content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="class-overview.csv"'})
