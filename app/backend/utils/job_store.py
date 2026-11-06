"""Durable SQLite queue with owner isolation, idempotency and fenced completion."""
import hashlib
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from utils import db, latex
from utils.gigachat_client import AIServiceError
from utils.worksheet import validate_worksheet
from utils.workspace_store import connection, result_links, timestamp, record_edition

ACTIVE = ('queued', 'running')
TERMINAL = ('succeeded', 'failed', 'cancelled')
LANES = {'recognize': 'ai', 'variant': 'ai', 'compile': 'compile', 'grade': 'ai', 'report_pdf': 'compile', 'batch_grade':'ai'}
LABELS = {'recognize': 'Распознаём задания и готовим ответы', 'variant': 'Готовим новый вариант', 'compile': 'Собираем лист, ответы и Marp', 'grade': 'Распознаём ответы ученика', 'report_pdf': 'Готовим PDF отчёта класса','batch_grade':'Проверяем пачку сканов класса'}
LANES.update(analytics_pdf='compile',analytics_insight='ai')
LABELS.update(analytics_pdf='Собираем подробный отчёт',analytics_insight='Готовим рекомендации по статистике')
LANES['roster_recognize'] = 'ai'
LANES['answer_forms'] = 'compile'
LABELS['answer_forms'] = 'Готовим бланки ответов'
LANES['student_grade'] = 'ai'
LABELS['student_grade'] = 'Распознаём присланную работу'
LANES['solution_review'] = 'ai'
LABELS['solution_review'] = 'Анализируем ход решения'
LANES['material_form'] = 'compile'
LABELS['material_form'] = 'Готовим бланк ответов A4'
LABELS['roster_recognize'] = 'Распознаём список учеников'
LEASE_SECONDS = 45
RETENTION_SECONDS = 7 * 86400


def root():
    directory = Path(os.environ.get('LISTOK_JOBS_DIR') or (Path(db.DB_PATH).resolve().parent / 'jobs')).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def job_directory(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('Invalid job directory')
    parent = root()
    target = (parent / job_id).resolve()
    if target.parent != parent:
        raise ValueError('Job path escaped its directory')
    return target


def remove_inputs(job_id):
    target = job_directory(job_id)
    if target.exists():
        shutil.rmtree(target)


def fingerprint(kind, payload, image_paths=()):
    digest = hashlib.sha256(json.dumps([kind, payload], sort_keys=True, ensure_ascii=False).encode())
    images = []
    for path in image_paths:
        file_digest = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                file_digest.update(chunk)
        images.append(file_digest.digest())
    if kind == 'review_photo':
        if len(set(images)) != len(images):
            raise AIServiceError('Одно и то же фото добавлено несколько раз. Уберите повтор.', 'duplicate_photo', 400)
        images.sort()
    for image_digest in images:
        digest.update(image_digest)
    return digest.hexdigest()


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
        raise AIServiceError('Обновите страницу и повторите действие.', 'invalid_request_key', 400)
    return key


def _public(row, conn):
    position = 0
    if row['status'] == 'queued':
        position = conn.execute("SELECT COUNT(*) FROM jobs WHERE lane=? AND status='queued' AND (created_at<? OR (created_at=? AND id<=?))",
                                (row['lane'], row['created_at'], row['created_at'], row['id'])).fetchone()[0]
    return {'id': row['id'], 'request_key': row['request_key'], 'kind': row['kind'], 'status': row['status'], 'position': position,
            'label': LABELS[row['kind']], 'created_at': row['created_at'], 'started_at': row['started_at'],
            'result': json.loads(row['result']) if row['result'] else None,
            'error': row['error'], 'error_code': row['error_code']}


def _owned(conn, owner, job_id):
    row = conn.execute('SELECT * FROM jobs WHERE id=? AND owner_id=?', (job_id, owner)).fetchone()
    if row is None:
        raise AIServiceError('Задача не найдена в вашем профиле.', 'job_not_found', 404)
    return row


def get_job(owner, job_id):
    with connection() as conn:
        return _public(_owned(conn, owner, job_id), conn)


def list_jobs(owner):
    with connection() as conn:
        rows = conn.execute('SELECT * FROM jobs WHERE owner_id=? AND acknowledged=0 ORDER BY created_at DESC LIMIT 50', (owner,)).fetchall()
        return [_public(row, conn) for row in rows]


def workers_ready(lane=None):
    with connection() as conn:
        rows = conn.execute('SELECT DISTINCT lane FROM workers WHERE heartbeat>?', (time.time() - 20,)).fetchall()
    alive = {row['lane'] for row in rows}
    return lane in alive if lane else {'ai': 'ai' in alive, 'compile': 'compile' in alive}


def heartbeat(worker, lane, job_id=None, claim=None):
    now = time.time()
    with connection() as conn:
        conn.execute('INSERT INTO workers VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat', (worker, lane, now))
        if job_id:
            conn.execute("UPDATE jobs SET heartbeat=?,updated_at=? WHERE id=? AND claim=? AND status='running'", (now, now, job_id, claim))


def submit(owner, kind, request_key, payload, image_paths=(), require_worker=True):
    validate_key(request_key)
    if kind not in LANES:
        raise AIServiceError('Неизвестное действие.', 'invalid_job_kind', 400)
    signature = fingerprint(kind, payload, image_paths)
    job_id = uuid.uuid4().hex
    directory = job_directory(job_id)
    created = False
    try:
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT * FROM jobs WHERE owner_id=? AND request_key=?', (owner, request_key)).fetchone()
            if previous:
                if previous['fingerprint'] != signature:
                    raise AIServiceError('Этот запрос уже использован для другого содержания. Повторите действие заново.', 'request_key_conflict', 409)
                return _public(previous, conn), False
            if require_worker and not conn.execute('SELECT 1 FROM workers WHERE lane=? AND heartbeat>?', (LANES[kind], time.time() - 20)).fetchone():
                raise AIServiceError('Обработка временно недоступна. Сохраните черновик и повторите позже.', 'worker_unavailable', 503)
            if conn.execute("SELECT 1 FROM jobs WHERE owner_id=? AND status IN ('queued','running')", (owner,)).fetchone():
                raise AIServiceError('У вас уже есть задача. Дождитесь её результата — он появится в разделе «Задачи».', 'owner_job_limit', 429)
            if conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 30:
                raise AIServiceError('Сейчас много запросов. Попробуйте через несколько минут.', 'queue_full', 429)
            if kind in ('recognize', 'variant') and conn.execute('SELECT COUNT(*) FROM materials WHERE owner_id=?', (owner,)).fetchone()[0] + payload.get('variant_count', 1) > 500:
                raise AIServiceError('В профиле можно хранить до 500 листов. Освободите место для новых вариантов.', 'materials_limit', 409)
            # Validate the saved snapshot in the same transaction as enqueueing.
            material_id = payload.get('material_id')
            if material_id:
                material = conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone()
                if material is None:
                    raise AIServiceError('Сохранённый лист не найден.', 'material_not_found', 404)
                if (type(payload.get('revision')) is not int or material['revision'] != payload['revision']
                        or validate_worksheet(json.loads(material['worksheet'])) != validate_worksheet(payload['worksheet'])):
                    raise AIServiceError('Лист изменился. Откройте свежую версию перед обработкой.', 'revision_conflict', 409)
            directory.mkdir()
            created = True
            stored = dict(payload)
            if kind == 'roster_recognize':
                from utils import class_store
                class_store.owned_class(conn, owner, payload['class_id'], active=True)
            if kind in ('analytics_pdf','analytics_insight'):
                from utils import analytics,analytics_ai
                stored['report']=analytics.overview(owner,payload.get('filters',{}),conn)
                if not stored['report']['totals']['confirmed']:
                    raise AIServiceError('Сначала подтвердите хотя бы одну проверку работы.','no_confirmed_scores',409)
                if kind=='analytics_pdf' and payload.get('insight_id'):
                    insight=conn.execute('SELECT * FROM analytics_insights WHERE id=? AND owner_id=?',(payload['insight_id'],owner)).fetchone()
                    if not insight or insight['snapshot_hash']!=analytics_ai.digest(stored['report']):
                        raise AIServiceError('Статистика изменилась. Обновите рекомендации или сформируйте PDF без них.','insight_stale',409)
                    stored['report']['insight']=json.loads(insight['content'])
            if kind == 'answer_forms':
                from utils import class_store
                if payload.get('mode') not in ('class', 'blank'):
                    raise AIServiceError('Выберите вид бланка.', 'invalid_answer_form', 400)
                stored['assignment'] = class_store.assignment_detail(conn, owner, payload.get('assignment_id'))
            if kind == 'material_form':
                edition=conn.execute('SELECT worksheet FROM editions WHERE id=? AND owner_id=?',(payload.get('edition_id'),owner)).fetchone()
                if edition is None:raise AIServiceError('Версия листа не найдена.','edition_not_found',404)
                stored['worksheet']=json.loads(edition['worksheet'])
            if kind == 'report_pdf':
                from utils import review_store
                stored['report'] = review_store.report(owner, payload.get('assignment_id'), conn)
            if kind == 'grade':
                from utils import review_store
                assignment = review_store.enqueue(conn, owner, job_id, payload, fingerprint('review_photo', {}, image_paths))
                stored['tasks'] = assignment['worksheet']['tasks']
            if kind == 'student_grade':
                from utils import student_store
                assignment=student_store.enqueue(conn,owner,payload.get('attempt_id'),job_id,payload.get('revision'))
                stored['tasks']=assignment['worksheet']['tasks']
            if kind == 'solution_review':
                from utils import solution_store
                analysis_row,assignment,_=solution_store.context(conn,owner,payload.get('target_kind'),payload.get('target_id'))
                if analysis_row['revision']!=payload.get('base_revision'):
                    raise AIServiceError('Работа изменилась. Откройте её заново.','revision_conflict',409)
                stored['tasks']=assignment['worksheet']['tasks']
                stored['subject']=assignment['worksheet']['subject']
            if kind == 'batch_grade':
                from utils import batch_review
                assignment = batch_review.enqueue(conn,owner,job_id,payload,fingerprint('batch_pdf',{},image_paths))
                stored['tasks'] = assignment['worksheet']['tasks']
            if material_id:
                stored['source'] = material['source']
                origin = conn.execute('SELECT author,title FROM material_origins WHERE material_id=?', (material_id,)).fetchone()
                stored['origin'] = dict(origin) if origin else None
            stored['images'] = []
            for i, image in enumerate(image_paths):
                name = str(i) + Path(image).suffix.lower()
                shutil.copyfile(image, directory / name)
                stored['images'].append(name)
            now = time.time()
            conn.execute('''INSERT INTO jobs (id,owner_id,kind,lane,request_key,fingerprint,payload,status,created_at,updated_at)
                            VALUES (?,?,?,?,?,?,?,'queued',?,?)''',
                         (job_id, owner, kind, LANES[kind], request_key, signature, json.dumps(stored, ensure_ascii=False), now, now))
            result = _public(_owned(conn, owner, job_id), conn)
            if payload.get('_bot_user') and owner==f"max:{payload['_bot_user']}":
                conn.execute('INSERT INTO bot_runs(job_id,user_id,created_at) VALUES(?,?,?)',(job_id,payload['_bot_user'],now))
        return result, True
    except BaseException:
        if created:
            remove_inputs(job_id)
        raise


def claim_next(lane):
    if lane not in ('ai', 'compile'):
        raise ValueError('Invalid lane')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM jobs WHERE lane=? AND status='running'", (lane,)).fetchone():
            return None
        row = conn.execute("SELECT * FROM jobs WHERE lane=? AND status='queued' ORDER BY created_at,id LIMIT 1", (lane,)).fetchone()
        if row is None:
            return None
        now, claim = time.time(), uuid.uuid4().hex
        conn.execute("UPDATE jobs SET status='running',claim=?,started_at=?,heartbeat=?,updated_at=? WHERE id=?", (claim, now, now, now, row['id']))
        return dict(conn.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())


def fail(job_id, claim, message, code):
    with connection() as conn:
        now = time.time()
        return bool(conn.execute("UPDATE jobs SET status='failed',error=?,error_code=?,finished_at=?,updated_at=? WHERE id=? AND claim=? AND status='running'",
                                 (message, code, now, now, job_id, claim)).rowcount)


def complete(job, output, active_connection=None):
    """Commit saved material/artifact and result together; a stale worker cannot publish."""
    with (nullcontext(active_connection) if active_connection is not None else connection()) as conn:
        if not conn.in_transaction:
            conn.execute('BEGIN IMMEDIATE')
        current = conn.execute("SELECT * FROM jobs WHERE id=? AND claim=? AND status='running'", (job['id'], job['claim'])).fetchone()
        if current is None:
            return False
        payload, now = json.loads(current['payload']), timestamp()
        owner, job_id = current['owner_id'], current['id']
        if current['kind'] == 'compile':
            # All file names are deterministic and supplied by our worker, never by a client.
            base = 'job_' + job_id
            conn.execute('INSERT INTO artifacts (id,owner_id,pdf,answers,tex,created_at,marp) VALUES (?,?,?,?,?,?,?)',
                         (job_id, owner, base + '.pdf', base + '_keys.pdf', base + '.tex', now, base + '_marp.zip'))
            if (Path(latex.OUTPUT_DIR)/(base+'_teacher.pdf')).is_file():
                conn.execute('UPDATE artifacts SET teacher=? WHERE id=?',(base+'_teacher.pdf',job_id))
            if (Path(latex.OUTPUT_DIR)/(base+'_answer_form.pdf')).is_file():
                conn.execute('UPDATE artifacts SET answer_form=? WHERE id=?',(base+'_answer_form.pdf',job_id))
            material = conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?', (payload['material_id'], owner)).fetchone()
            record_edition(conn, job_id, owner, material['id'] if material else None, payload['worksheet'], payload['revision'])
            attached = material is not None and material['revision'] == payload['revision']
            if attached:
                conn.execute('UPDATE artifacts SET material_id=NULL WHERE material_id=? AND owner_id=?', (material['id'], owner))
                conn.execute('UPDATE artifacts SET material_id=? WHERE id=?', (material['id'], job_id))
                conn.execute('UPDATE materials SET updated_at=? WHERE id=?', (now, material['id']))
            result = {'worksheet': payload['worksheet'], 'source': payload.get('source', 'manual'),
                      'material_id': material['id'] if attached else None, 'attached': attached,
                      **result_links(conn.execute('SELECT * FROM artifacts WHERE id=?', (job_id,)).fetchone())}
        elif current['kind'] == 'roster_recognize':
            from utils import roster_store
            result = roster_store.complete(job_id, payload['class_id'], output)
        elif current['kind'] == 'analytics_insight':
            from utils import analytics_ai
            content=output.get('insight')
            if not isinstance(content,dict) or any(not isinstance(content.get(k),list) or not 1<=len(content[k])<=5 or any(not isinstance(x,str) or len(x)>600 for x in content[k]) for k in ('observations','actions')):
                raise AIServiceError('Некорректные рекомендации.','insight_invalid',502)
            conn.execute('INSERT INTO analytics_insights VALUES(?,?,?,?,?)',(job_id,owner,analytics_ai.digest(payload['report']),json.dumps(content,ensure_ascii=False),now))
            result={'insight_id':job_id,'insight':content,'generated_at':payload['report']['generated_at'],'filters':payload['filters']}
        elif current['kind'] in ('report_pdf','analytics_pdf','answer_forms','material_form'):
            base = 'job_' + job_id
            path = Path(latex.OUTPUT_DIR) / (base + '.pdf')
            if not path.is_file() or not path.with_suffix('.tex').is_file():
                raise AIServiceError('PDF отчёта не найден.', 'report_missing', 500)
            with path.open('rb') as stream:
                if stream.read(5) != b'%PDF-':
                    raise AIServiceError('PDF отчёта повреждён.', 'report_missing', 500)
            conn.execute('INSERT INTO artifacts (id,owner_id,pdf,tex,created_at) VALUES (?,?,?,?,?)',
                         (job_id, owner, base + '.pdf', base + '.tex', now))
            if current['kind'] == 'material_form':
                conn.execute('UPDATE artifacts SET answer_form=? WHERE id=? AND owner_id=?',(base+'.pdf',payload['edition_id'],owner))
                result={'edition_id':payload['edition_id']}
            elif current['kind'] == 'answer_forms':
                conn.execute('INSERT INTO answer_form_exports VALUES (?,?,?)', (job_id, payload['assignment_id'], payload['mode']))
                result = {'assignment_id': payload['assignment_id'], 'mode': payload['mode'], 'generated_at': now}
            else:
                result = {**({'assignment_id':payload['assignment_id'],'edition_code':payload['report']['edition_code']} if current['kind']=='report_pdf' else {'filters':payload['filters']}),
                          'generated_at': payload['report']['generated_at']}
            result.update(result_links(conn.execute('SELECT * FROM artifacts WHERE id=?', (job_id,)).fetchone()))
        elif current['kind'] == 'batch_grade':
            from utils import batch_review
            result = batch_review.complete(conn,owner,job_id,output,job_directory(job_id)/'pages')
        elif current['kind'] == 'grade':
            from utils import review_store
            directory = job_directory(job_id) / 'pages'
            names = output.get('photos', [])
            if not isinstance(names, list) or not 1 <= len(names) <= 5 or len(names) != len(payload.get('images', [])) or any(not isinstance(n, str) or not re.fullmatch(r'page_[1-5]\.jpg', n) for n in names) or len(set(names)) != len(names):
                raise AIServiceError('Не найдены обработанные фотографии.', 'invalid_recognition', 502)
            result = review_store.complete(conn, owner, job_id, output, [directory / n for n in names])
        elif current['kind'] == 'solution_review':
            analysis=output.get('analysis')
            if not isinstance(analysis,dict) or not isinstance(analysis.get('tasks'),list):
                raise AIServiceError('Анализ не получен.','analysis_invalid',502)
            conn.execute('INSERT INTO solution_analyses VALUES(?,?,?,?,?,?,?)',(job_id,owner,payload['target_kind'],payload['target_id'],payload['base_revision'],json.dumps(analysis,ensure_ascii=False),now))
            result={'target_kind':payload['target_kind'],'target_id':payload['target_id']}
        elif current['kind'] == 'student_grade':
            from utils import student_store
            names=output.get('photos',[])
            if not isinstance(names,list) or not 1<=len(names)<=10 or len(set(names))!=len(names) or any(not isinstance(n,str) or not re.fullmatch(r'page_(?:[1-9]|10)\.jpg',n) for n in names):
                raise AIServiceError('Не найдены страницы работы.','invalid_recognition',502)
            result=student_store.complete(conn,owner,payload['attempt_id'],job_id,output,[job_directory(job_id)/'pages'/n for n in names])
        else:
            worksheets = output.get('worksheets', [output.get('worksheet')])
            requested = payload.get('variant_count', 1)
            if not isinstance(worksheets, list) or not 1 <= len(worksheets) <= requested <= 4:
                raise AIServiceError('Неверный результат обработки вариантов.', 'invalid_batch', 502)
            worksheets = [validate_worksheet(w) for w in worksheets]
            origin = None
            if payload.get('material_id'):
                origin = conn.execute('SELECT * FROM material_origins WHERE material_id=?', (payload['material_id'],)).fetchone()
            materials = []
            for index, worksheet in enumerate(worksheets):
                material_id = job_id if index == 0 else uuid.uuid5(uuid.UUID(job_id), str(index)).hex
                conn.execute('INSERT INTO materials VALUES (?,?,?,?,1,?,?)',
                             (material_id, owner, json.dumps(worksheet, ensure_ascii=False), 'ai_draft', now, now))
                if origin:
                    conn.execute('INSERT INTO material_origins VALUES (?,?,?,?)', (material_id, origin['publication_id'], origin['author'], origin['title']))
                materials.append({'material_id': material_id, 'title': worksheet['title'], 'variant': worksheet['settings']['variant']})
                if payload.get('auto_compile') is True and conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] < 30:
                    preview_id=uuid.uuid5(uuid.UUID(material_id),'preview-pdf').hex
                    preview={'worksheet':worksheet,'material_id':material_id,'revision':1,'source':'ai_draft','images':[],'auto_preview':True}
                    queued_at=time.time()+index*.001
                    conn.execute('''INSERT INTO jobs (id,owner_id,kind,lane,request_key,fingerprint,payload,status,created_at,updated_at)
                                    VALUES (?,?,'compile','compile',?,?,?,'queued',?,?)''',
                                 (preview_id,owner,'preview-'+material_id,fingerprint('compile',preview),json.dumps(preview,ensure_ascii=False),queued_at,queued_at))
                    materials[-1]['compile_job_id']=preview_id
            result = {'material_id': job_id, 'materials': materials, 'requested_count': requested,
                      'warning': output.get('warning', '')[:1000]}
            if payload.get('auto_compile') and any(not m.get('compile_job_id') for m in materials):
                result['warning'] += ' Очередь печати заполнена. Оставшиеся листы сохранены в библиотеке: откройте их и нажмите «Собрать PDF».'
        completed = time.time()
        conn.execute("UPDATE jobs SET status='succeeded',result=?,finished_at=?,updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), completed, completed, job_id))
        return True


def acknowledge(owner, job_id):
    with connection() as conn:
        row = _owned(conn, owner, job_id)
        if row['status'] not in TERMINAL:
            raise AIServiceError('Задача ещё выполняется.', 'job_active', 409)
        conn.execute('UPDATE jobs SET acknowledged=1 WHERE id=? AND owner_id=?', (job_id, owner))


def cancel(owner, job_id):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _owned(conn, owner, job_id)
        if row['status'] == 'running':
            raise AIServiceError('Обработка уже началась. Можно закрыть приложение — результат сохраним в профиле.', 'job_running', 409)
        if row['status'] == 'queued':
            now = time.time()
            conn.execute("UPDATE jobs SET status='cancelled',finished_at=?,updated_at=? WHERE id=?", (now, now, job_id))
    if row['status'] == 'queued':
        remove_inputs(job_id)
    return get_job(owner, job_id)


def maintain():
    now = time.time()
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Recover already generated drafts after a worker/machine restart without
        # making any new provider request. The claim and result are committed together.
        expired = conn.execute("SELECT * FROM jobs WHERE status='running' AND heartbeat<? AND kind!='compile'", (now - LEASE_SECONDS,)).fetchall()
        for row in expired:
            path = job_directory(row['id']) / 'result.json'
            try:
                if path.is_file() and path.stat().st_size <= 2 * 1024 * 1024:
                    output = json.loads(path.read_text(encoding='utf-8'))
                    if output.get('worksheets') or (row['kind'] == 'grade' and isinstance(output.get('answers'), list) and output.get('photos')) or (row['kind']=='batch_grade' and output.get('batch_pages')):
                        complete(dict(row), output, conn)
            except (ValueError, AIServiceError, OSError):
                pass
        conn.execute("""UPDATE jobs SET status='failed',error='Обработка прервалась. Повторите действие вручную; автоматического повторного запроса к ИИ не было.',
                        error_code='worker_interrupted',finished_at=?,updated_at=? WHERE status='running' AND heartbeat<?""", (now, now, now - LEASE_SECONDS))
        conn.execute("""UPDATE jobs SET status='failed',error='Время ожидания истекло. Повторите действие.',error_code='queue_expired',finished_at=?,updated_at=?
                        WHERE status='queued' AND created_at<?""", (now, now, now - 86400))
        from utils import roster_store
        roster_store.maintain(conn, now)
        terminal = [r['id'] for r in conn.execute("SELECT id FROM jobs WHERE status IN ('succeeded','failed','cancelled')")]
        from utils import review_store
        review_store.maintain(conn)
        from utils import student_store
        student_store.maintain(conn,now)
        from utils import batch_review
        batch_review.maintain(conn)
        conn.execute("DELETE FROM jobs WHERE finished_at<?", (now - RETENTION_SECONDS,))
        conn.execute('DELETE FROM workers WHERE heartbeat<?', (now - 86400,))
    for job_id in terminal:
        try:
            remove_inputs(job_id)
        except OSError:
            pass  # A just-killed Windows process may release a handle on the next pass.
