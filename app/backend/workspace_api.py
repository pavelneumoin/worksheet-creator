"""Structured worksheets and personal materials, protected by MAX sessions."""
import os
import tempfile
import uuid
import secrets
import time
from pathlib import Path

from flask import Blueprint, g, jsonify, request, send_from_directory

from utils import latex, structured_ai, workspace_store, library_store
from utils.gigachat_client import AIServiceError, get_ai_status
from utils.max_auth import validate_init_data
from utils.sessions import token_hash
from utils.worksheet import demo_worksheet, validate_worksheet, compile_worksheet

api = Blueprint("workspace", __name__, url_prefix="/api/v2")


def subject(value):
    if value not in ("math", "physics"):
        raise AIServiceError("Выберите математику или физику.", "invalid_subject", 400)
    return value


@api.get("/demo")
def demo():
    return jsonify(worksheet=demo_worksheet(subject(request.args.get("subject", "math"))),
                   source="manual_demo", requires_review=True,
                   message="Учебный пример подготовлен вручную. ИИ не использовался.")


@api.post("/recognize")
def recognize():
    discipline = subject(request.form.get("subject", "math"))
    files = [f for f in request.files.getlist("files") if f.filename]
    text = request.form.get("text", "").strip()
    if not files and not text:
        raise AIServiceError("Добавьте фотографии или текст заданий.", "no_input", 400)
    if len(files) > 10 or len(text) > 16000:
        raise AIServiceError("Добавьте до 10 фото или до 16000 символов текста.", "input_limit", 400)
    for item in files:
        extension = Path(item.filename).suffix.lower()
        header = item.stream.read(8)
        item.stream.seek(0, 2)
        size = item.stream.tell()
        item.stream.seek(0)
        if size > 15 * 1024 * 1024:
            raise AIServiceError("Одна фотография должна быть не больше 15 МБ.", "file_too_large", 413)
        if not ((extension == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n")) or
                (extension in (".jpg", ".jpeg") and header.startswith(b"\xff\xd8\xff"))):
            raise AIServiceError("Поддерживаются фотографии PNG и JPEG.", "invalid_image", 415)
    status = get_ai_status()
    if not status["ai_ready"]:
        raise AIServiceError(status["ai_message"], "ai_not_configured", 503)
    with tempfile.TemporaryDirectory(prefix="listok-input-") as temp:
        paths = []
        for item in files:
            path = Path(temp) / (uuid.uuid4().hex + Path(item.filename).suffix.lower())
            item.save(path)
            paths.append(str(path))
        worksheet = structured_ai.generate(discipline, image_paths=paths, text=text)
    return jsonify(worksheet=worksheet, source="ai_draft", requires_review=True)


@api.post("/variant")
def variant():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AIServiceError("Неверный запрос варианта.", "invalid_json", 400)
    worksheet = validate_worksheet(data.get("worksheet"))
    difficulty = data.get("difficulty", "same")
    if difficulty not in ("same", "easier", "harder"):
        raise AIServiceError("Неизвестный уровень сложности.", "invalid_difficulty", 400)
    result = structured_ai.generate(worksheet["subject"], original=worksheet, difficulty=difficulty)
    return jsonify(worksheet=result, source="ai_draft", requires_review=True)


@api.post("/compile")
def compile_document():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AIServiceError("Неверный запрос сборки.", "invalid_json", 400)
    worksheet = validate_worksheet(data.get("worksheet"))
    if data.get("reviewed") is not True:
        raise AIServiceError("Проверьте условия и ответы перед сборкой.", "review_required", 400)
    if not latex.get_latex_compiler():
        raise AIServiceError("Компилятор PDF не настроен на сервере.", "latex_unavailable", 503)
    base = "sheet_" + uuid.uuid4().hex
    pdf, keys = compile_worksheet(worksheet, base)
    links = workspace_store.add_artifact(g.identity['owner_id'], pdf, keys, f'{base}.tex')
    return jsonify(**links, message="Лист и ответы готовы. Проверьте предпросмотр перед печатью.")


@api.get('/materials')
def list_materials():
    return jsonify(materials=workspace_store.list_materials(g.identity['owner_id']))


@api.get('/materials/<material_id>')
def get_material(material_id):
    return jsonify(material=workspace_store.get_material(g.identity['owner_id'], material_id))


@api.post('/materials')
@api.put('/materials/<material_id>')
def save_material(material_id=None):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AIServiceError('Передайте рабочий лист.', 'invalid_json', 400)
    worksheet = validate_worksheet(data.get('worksheet'))
    source = data.get('source', 'manual')
    if source not in ('manual', 'manual_demo', 'ai_draft', 'browser_import', 'community'):
        raise AIServiceError('Неизвестный источник материала.', 'invalid_source', 400)
    artifact_id = data.get('artifact_id')
    if artifact_id is not None and (not isinstance(artifact_id, str) or len(artifact_id) > 64):
        raise AIServiceError('Неверный файл.', 'invalid_artifact', 400)
    origin_id = data.get('origin_material_id')
    if origin_id is not None and (not isinstance(origin_id, str) or len(origin_id) > 64):
        raise AIServiceError('Неверный исходный материал.', 'invalid_origin', 400)
    result = workspace_store.put_material(g.identity['owner_id'], worksheet, source, material_id,
                                          data.get('revision'), artifact_id, origin_id)
    return jsonify(material=result), 200 if material_id else 201


@api.delete('/materials/<material_id>')
def delete_material(material_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise AIServiceError('Неверный запрос.', 'invalid_json', 400)
    files = workspace_store.delete_material(g.identity['owner_id'], material_id, data.get('revision'))
    for filename in files:
        if Path(filename).name == filename:
            (Path(latex.OUTPUT_DIR) / filename).unlink(missing_ok=True)
    return jsonify(deleted=True)


def library_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AIServiceError('Неверный запрос библиотеки.', 'invalid_json', 400)
    return data


@api.get('/library')
def list_library():
    try:
        page = int(request.args.get('page', '1'))
    except ValueError:
        raise AIServiceError('Неверная страница библиотеки.', 'invalid_page', 400)
    return jsonify(**library_store.list_publications(g.identity['owner_id'],
                   request.args.get('q', ''), request.args.get('subject', ''),
                   request.args.get('sort', 'rating'), page))


@api.get('/library/<publication_id>')
def get_publication(publication_id):
    return jsonify(publication=library_store.get_publication(g.identity['owner_id'], publication_id))


@api.post('/materials/<material_id>/publish')
def publish_material(material_id):
    data = library_body()
    publication = library_store.publish(g.identity['owner_id'], material_id, data.get('revision'),
                                        data.get('author'), data.get('description', ''), data.get('reviewed'))
    return jsonify(publication=publication), 201


@api.delete('/library/<publication_id>')
def withdraw_publication(publication_id):
    library_store.withdraw(g.identity['owner_id'], publication_id)
    return jsonify(deleted=True)


@api.put('/library/<publication_id>/rating')
def rate_publication(publication_id):
    return jsonify(publication=library_store.rate(g.identity['owner_id'], publication_id, library_body().get('stars')))


@api.post('/library/<publication_id>/copy')
def copy_publication(publication_id):
    return jsonify(material=library_store.copy_to_materials(g.identity['owner_id'], publication_id)), 201


@api.post('/exports/<artifact_id>')
def export_files(artifact_id):
    """Short-lived capability for native MAX downloads, which do not send cookies."""
    now, raw = int(time.time()), secrets.token_urlsafe(32)
    with workspace_store.connection() as conn:
        artifact = conn.execute('SELECT * FROM artifacts WHERE id=? AND owner_id=?',
                                (artifact_id, g.identity['owner_id'])).fetchone()
        if artifact is None:
            workspace_store.missing()
        conn.execute('DELETE FROM download_tickets WHERE expires_at<=?', (now,))
        conn.execute('INSERT INTO download_tickets VALUES (?,?,?,?)',
                     (token_hash(raw), g.identity['token_hash'], artifact_id, now + 600))
        urls = {name: f'/api/v2/downloads/{raw}/{artifact[column]}' for name, column in
                (('pdf_url','pdf'), ('keys_url','answers'), ('tex_url','tex'), ('marp_url','marp')) if artifact[column]}
    return jsonify(**urls, expires_at=now + 600)


@api.get('/downloads/<ticket>/<filename>')
def download_file(ticket, filename):
    if len(ticket) > 100 or Path(filename).name != filename:
        workspace_store.missing()
    with workspace_store.connection() as conn:
        now = int(time.time())
        row = conn.execute('''SELECT a.pdf,a.answers,a.tex,a.marp FROM download_tickets d
                              JOIN sessions s ON s.token_hash=d.session_hash
                              JOIN artifacts a ON a.id=d.artifact_id AND a.owner_id=s.owner_id
                              WHERE d.token_hash=? AND d.expires_at>? AND s.expires_at>?''',
                           (token_hash(ticket), now, now)).fetchone()
        if row is None or filename not in tuple(row):
            workspace_store.missing()
    return send_from_directory(str(Path(latex.OUTPUT_DIR).resolve()), filename, as_attachment=True)


@api.post("/max/validate")
def max_launch():
    """Integration readiness endpoint; not a login session or public access control."""
    token = os.environ.get("MAX_BOT_TOKEN", "").strip()
    if not token:
        raise AIServiceError("Бот MAX пока не подключён.", "max_not_configured", 503)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AIServiceError("Передайте данные запуска MAX.", "invalid_json", 400)
    user = validate_init_data(data.get("init_data"), token)
    return jsonify(valid=True, user=user, session_created=False)
