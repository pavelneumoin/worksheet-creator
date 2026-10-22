"""Fast enqueue/poll endpoints. Expensive work runs outside the web process."""
from pathlib import Path
import tempfile
import uuid

from flask import Blueprint, g, jsonify, request

from utils import job_store
from utils.gigachat_client import AIServiceError, get_ai_status
from utils.worksheet import validate_worksheet

api = Blueprint('jobs', __name__, url_prefix='/api/v2/jobs')


@api.get('')
def list_jobs():
    job_store.maintain()
    return jsonify(jobs=job_store.list_jobs(g.identity['owner_id']), workers=job_store.workers_ready())


@api.get('/<job_id>')
def get_job(job_id):
    job_store.maintain()
    return jsonify(job=job_store.get_job(g.identity['owner_id'], job_id))


@api.post('/<job_id>/acknowledge')
def acknowledge(job_id):
    job_store.acknowledge(g.identity['owner_id'], job_id)
    return jsonify(acknowledged=True)


@api.post('/<job_id>/cancel')
def cancel(job_id):
    return jsonify(job=job_store.cancel(g.identity['owner_id'], job_id))


def accepted(kind, payload, images=()):
    result, created = job_store.submit(g.identity['owner_id'], kind, request.headers.get('Idempotency-Key'), payload, images)
    return jsonify(job=result, reused=not created), 202 if result['status'] in job_store.ACTIVE else 200


@api.post('/recognize')
def recognize():
    job_store.validate_key(request.headers.get('Idempotency-Key'))
    discipline = request.form.get('subject', 'math')
    if discipline not in ('math', 'physics'):
        raise AIServiceError('Выберите математику или физику.', 'invalid_subject', 400)
    text = request.form.get('text', '').strip()
    files = [file for file in request.files.getlist('files') if file.filename]
    if not text and not files:
        raise AIServiceError('Добавьте фотографии или текст заданий.', 'no_input', 400)
    if len(text) > 16000 or len(files) > 10:
        raise AIServiceError('Добавьте до 10 фото или до 16000 символов текста.', 'input_limit', 400)
    status = get_ai_status()
    if not status['ai_ready']:
        raise AIServiceError(status['ai_message'], 'ai_not_configured', 503)
    with tempfile.TemporaryDirectory(prefix='listok-upload-') as temporary:
        paths = []
        for file in files:
            ext = Path(file.filename).suffix.lower()
            head = file.stream.read(8)
            file.stream.seek(0, 2)
            size = file.stream.tell()
            file.stream.seek(0)
            if size > 15 * 1024 * 1024:
                raise AIServiceError('Одна фотография должна быть не больше 15 МБ.', 'file_too_large', 413)
            if not ((ext == '.png' and head.startswith(b'\x89PNG\r\n\x1a\n')) or
                    (ext in ('.jpg', '.jpeg') and head.startswith(b'\xff\xd8\xff'))):
                raise AIServiceError('Поддерживаются фотографии PNG и JPEG.', 'invalid_image', 415)
            path = Path(temporary) / (uuid.uuid4().hex + ext)
            file.save(path)
            paths.append(path)
        return accepted('recognize', {'subject': discipline, 'text': text}, paths)


@api.post('/compile')
@api.post('/variant')
def worksheet_job():
    kind = request.path.rsplit('/', 1)[-1]
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AIServiceError('Передайте рабочий лист.', 'invalid_json', 400)
    worksheet = validate_worksheet(data.get('worksheet'))
    material_id = data.get('material_id')
    if not isinstance(material_id, str) or len(material_id) > 64 or not material_id:
        raise AIServiceError('Сначала сохраните черновик.', 'save_required', 400)
    payload = {'worksheet': worksheet, 'material_id': material_id, 'revision': data.get('revision')}
    if kind == 'compile':
        if data.get('reviewed') is not True:
            raise AIServiceError('Проверьте условия и ответы перед сборкой.', 'review_required', 400)
    else:
        difficulty = data.get('difficulty', 'same')
        if difficulty not in ('same', 'easier', 'harder'):
            raise AIServiceError('Неизвестный уровень сложности.', 'invalid_difficulty', 400)
        status = get_ai_status()
        if not status['ai_ready']:
            raise AIServiceError(status['ai_message'], 'ai_not_configured', 503)
        payload['difficulty'] = difficulty
    return accepted(kind, payload)
