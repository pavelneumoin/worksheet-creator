"""Fast enqueue/poll endpoints. Expensive work runs outside the web process."""
from pathlib import Path
import json
import tempfile
import uuid

from flask import Blueprint, g, jsonify, request

from utils import job_store
from utils.gigachat_client import AIServiceError, get_ai_status
from utils.worksheet import validate_worksheet
from class_api import body
from utils import class_store
from utils.workspace_store import connection

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


@api.post('/roster_recognize')
def roster_recognize():
    job_store.validate_key(request.headers.get('Idempotency-Key'))
    class_id = request.form.get('class_id', '')
    with connection() as conn:
        class_store.owned_class(conn, g.identity['owner_id'], class_id, active=True)
    if request.form.get('consent') != 'true':
        raise AIServiceError('Подтвердите отправку фотографии списка в GigaChat.', 'roster_consent', 400)
    files = [f for f in request.files.getlist('files') if f.filename]
    if not 1 <= len(files) <= 3:
        raise AIServiceError('Добавьте от 1 до 3 фотографий списка.', 'input_limit', 400)
    with tempfile.TemporaryDirectory(prefix='listok-roster-') as temporary:
        paths = []; total = 0
        for file in files:
            ext = Path(file.filename).suffix.lower()
            head = file.stream.read(8)
            file.stream.seek(0, 2); size = file.stream.tell(); file.stream.seek(0)
            total += size
            if size > 15 * 1024 * 1024 or total > 20 * 1024 * 1024:
                raise AIServiceError('До 15 МБ на фото и до 20 МБ всего.', 'file_too_large', 413)
            if not ((ext == '.png' and head.startswith(b'\x89PNG\r\n\x1a\n')) or
                    (ext in ('.jpg', '.jpeg') and head.startswith(b'\xff\xd8\xff'))):
                raise AIServiceError('Для списка поддерживаются фотографии PNG и JPEG.', 'invalid_image', 415)
            path = Path(temporary) / (uuid.uuid4().hex + ext)
            file.save(path); paths.append(path)
        job_store.fingerprint('review_photo', {}, paths)  # Reject repeated copies of the same photo.
        status = get_ai_status()
        if not status['ai_ready']:
            raise AIServiceError(status['ai_message'], 'ai_not_configured', 503)
        return accepted('roster_recognize', {'class_id': class_id}, paths)


@api.get('/<job_id>/roster')
@api.delete('/<job_id>/roster')
def roster_result(job_id):
    from utils import roster_store
    return jsonify(roster_store.get(g.identity['owner_id'], job_id, discard=request.method == 'DELETE'))


@api.post('/answer_forms')
def answer_forms():
    data = body()
    if set(data) != {'assignment_id', 'mode'} or data.get('mode') not in ('class', 'blank') or not isinstance(data['assignment_id'], str):
        raise AIServiceError('Выберите назначенную работу и вид бланка.', 'invalid_answer_form', 400)
    with connection() as conn:
        class_store.assignment_detail(conn, g.identity['owner_id'], data['assignment_id'])
    return accepted('answer_forms', data)


@api.post('/material_form')
def material_form():
    data=body()
    if set(data)!={'edition_id'} or not isinstance(data['edition_id'],str):
        raise AIServiceError('Выберите готовую версию листа.','invalid_edition',400)
    return accepted('material_form',data)


@api.post('/report_pdf')
def report_pdf():
    data = body()
    if set(data) != {'assignment_id'} or not isinstance(data['assignment_id'], str):
        raise AIServiceError('Выберите назначенную работу для отчёта.', 'invalid_report', 400)
    with connection() as conn:
        class_store.assignment_detail(conn, g.identity['owner_id'], data['assignment_id'])
    return accepted('report_pdf', data)


@api.post('/recognize')
def recognize():
    job_store.validate_key(request.headers.get('Idempotency-Key'))
    discipline = request.form.get('subject', 'math')
    if discipline not in ('math', 'physics', 'chemistry', 'other'):
        raise AIServiceError('Выберите математику, физику, химию или другой предмет.', 'invalid_subject', 400)
    text = request.form.get('text', '').strip()
    files = [file for file in request.files.getlist('files') if file.filename]
    if not text and not files:
        raise AIServiceError('Добавьте фотографии, PDF или текст заданий.', 'no_input', 400)
    if len(text) > 16000 or len(files) > 10:
        raise AIServiceError('Добавьте до 10 фото, один PDF или до 16000 символов текста.', 'input_limit', 400)
    pdf_count = sum(Path(f.filename).suffix.lower() == '.pdf' for f in files)
    if pdf_count and (pdf_count != 1 or len(files) != 1):
        raise AIServiceError('Загрузите один PDF или фотографии. PDF и фото обрабатываются отдельно.', 'input_limit', 400)
    instructions = request.form.get('instructions', '').strip()
    if len(instructions) > 2000 or '\x00' in instructions:
        raise AIServiceError('Пожелания к листу — до 2000 символов.', 'invalid_instructions', 400)
    try:
        settings = json.loads(request.form.get('settings', '{}'))
        count = json.loads(request.form.get('variant_count', '1'))
    except (ValueError, TypeError) as exc:
        raise AIServiceError('Проверьте настройки листа.', 'invalid_settings', 400) from exc
    count = variant_count(count)
    settings = validate_worksheet({'schema_version': 1, 'tasks': [{'question': 'Проверка настроек'}], 'settings': settings})['settings']
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
                raise AIServiceError('Один файл должен быть не больше 15 МБ.', 'file_too_large', 413)
            if not ((ext == '.png' and head.startswith(b'\x89PNG\r\n\x1a\n')) or
                    (ext in ('.jpg', '.jpeg') and head.startswith(b'\xff\xd8\xff')) or
                    (ext == '.pdf' and head.startswith(b'%PDF-'))):
                raise AIServiceError('Поддерживаются PNG, JPEG и PDF без пароля.', 'invalid_image', 415)
            path = Path(temporary) / (uuid.uuid4().hex + ext)
            file.save(path)
            paths.append(path)
        return accepted('recognize', {'subject': discipline, 'text': text, 'instructions': instructions,
                                     'settings': settings, 'variant_count': count,
                                     'auto_compile': request.form.get('auto_compile') == 'true'}, paths)


def variant_count(value):
    if type(value) is not int or not 1 <= value <= 4:
        raise AIServiceError('Выберите от 1 до 4 вариантов.', 'invalid_variant_count', 400)
    return value


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
        payload['variant_count'] = variant_count(data.get('variant_count', 1))
        payload['auto_compile'] = data.get('auto_compile') is True
    return accepted(kind, payload)
