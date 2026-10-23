"""Teacher-reviewed final answers, immutable assigned keys and class aggregates."""
from contextlib import nullcontext
import json
from pathlib import Path
import re
import shutil
import time
import uuid

from utils import db, class_store
from utils.answer_check import hint
from utils.gigachat_client import AIServiceError
from utils.workspace_store import connection, timestamp

PHOTO_RETENTION = 7 * 86400


def fail(message, code='invalid_review', status=400):
    raise AIServiceError(message, code, status)


def photo_root():
    # Lives with the persistent database volume, outside the web static directory.
    target = Path(db.DB_PATH).resolve().parent / 'review_photos'
    target.mkdir(parents=True, exist_ok=True)
    return target


def photo_path(review_id, index):
    if not re.fullmatch(r'[a-f0-9]{32}', review_id) or type(index) is not int or not 0 <= index < 10:
        fail('Фото не найдено.', 'photo_not_found', 404)
    target = photo_root() / review_id / f'{index}.jpg'
    if target.resolve().parent != photo_root() / review_id or target.is_symlink():
        fail('Фото не найдено.', 'photo_not_found', 404)
    return target


def owned(conn, owner, review_id):
    row = conn.execute('SELECT * FROM reviews WHERE id=? AND owner_id=?', (review_id, owner)).fetchone()
    if row is None:
        fail('Проверка не найдена.', 'review_not_found', 404)
    return row


def context(conn, owner, assignment_id, student_id):
    assignment = class_store.assignment_detail(conn, owner, assignment_id)
    if not any(s['id'] == student_id for s in assignment['students']):
        fail('Выберите ученика из состава этой работы.', 'student_not_assigned', 404)
    return assignment


def enqueue(conn, owner, review_id, payload, fingerprint):
    assignment = context(conn, owner, payload.get('assignment_id'), payload.get('student_id'))
    if conn.execute('SELECT 1 FROM reviews WHERE assignment_id=? AND student_id=?', (assignment['id'], payload['student_id'])).fetchone():
        fail('У этого ученика уже есть работа. Откройте её; неудачную или черновую проверку можно удалить перед новой загрузкой.', 'review_exists', 409)
    if conn.execute('SELECT 1 FROM reviews WHERE assignment_id=? AND fingerprint=?', (assignment['id'], fingerprint)).fetchone():
        fail('Эти фотографии уже прикреплены к другому ученику этой работы. Проверьте код.', 'duplicate_submission', 409)
    now = timestamp()
    conn.execute('''INSERT INTO reviews(id,owner_id,assignment_id,student_id,job_id,fingerprint,photo_expires,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                 (review_id, owner, assignment['id'], payload['student_id'], review_id, fingerprint, time.time() + PHOTO_RETENTION, now, now))
    return assignment


def audit(conn, row, action):
    snapshot = {k: row[k] for k in ('status', 'answers', 'warnings', 'comment', 'confirmed_at')}
    conn.execute('INSERT INTO review_history VALUES(?,?,?,?,?)',
                 (row['id'], row['revision'], action, json.dumps(snapshot, ensure_ascii=False), timestamp()))


def validate_recognition(value, tasks):
    if not isinstance(value, dict) or not isinstance(value.get('answers'), list) or len(value['answers']) > len(tasks):
        fail('ИИ вернул неверный список ответов. Загрузите более чёткое фото.', 'invalid_recognition', 502)
    expected = {t['id'] for t in tasks}
    found = {}
    for item in value['answers']:
        if not isinstance(item, dict) or not isinstance(item.get('task_id'), str) or item['task_id'] not in expected or item['task_id'] in found:
            fail('ИИ перепутал номера заданий. Проверьте фото и повторите загрузку.', 'invalid_recognition', 502)
        state, text = item.get('state'), item.get('text')
        if state not in ('readable', 'blank', 'unclear') or not isinstance(text, str) or len(text) > 2000 or '\x00' in text:
            fail('Не удалось надёжно распознать ответы.', 'invalid_recognition', 502)
        if state == 'readable' and not text.strip():
            state = 'unclear'
        found[item['task_id']] = {'task_id': item['task_id'], 'text': text.strip() if state != 'blank' else '', 'state': state}
    # An omitted number might be on a missing page; it is never a guessed blank.
    return [found.get(t['id'], {'task_id': t['id'], 'text': '', 'state': 'unclear'}) for t in tasks]


def complete(conn, owner, review_id, output, paths):
    row = owned(conn, owner, review_id)
    if row['status'] != 'processing':
        fail('Проверка уже изменена.', 'revision_conflict', 409)
    assignment = context(conn, owner, row['assignment_id'], row['student_id'])
    answers = validate_recognition(output, assignment['worksheet']['tasks'])
    warnings = []
    page_codes = output.get('page_codes', [output])
    if not isinstance(page_codes, list) or len(page_codes) != len(paths) or any(not isinstance(p, dict) for p in page_codes):
        fail('Не удалось сопоставить страницы ответов.', 'invalid_recognition', 502)
    for page_index, codes in enumerate(page_codes, 1):
        for name, expected, title in [('edition_code', assignment['code'], 'версии листа'),
                                      ('student_code', class_store.student_code(row['student_id']), 'ученика')]:
            seen = codes.get(name, '')
            if not isinstance(seen, str) or len(seen) > 80 or '\x00' in seen:
                fail('Неверный ответ распознавания.', 'invalid_recognition', 502)
            normalized_code = seen.upper().replace(' ', '')
            if name == 'student_code':
                normalized_code = re.sub(r'^[YУ]-', 'У-', normalized_code)
            if seen and normalized_code != expected.upper():
                warnings.append(f'На фото {page_index} прочитан другой код {title}: {seen}. Сверьте оригинал перед подтверждением.')
    conflicts = output.get('conflict_task_ids', [])
    task_numbers = {task['id']: str(i) for i, task in enumerate(assignment['worksheet']['tasks'], 1)}
    if not isinstance(conflicts, list) or len(conflicts) > len(answers) or any(not isinstance(i, str) or i not in task_numbers for i in conflicts):
        fail('Не удалось сопоставить ответы на страницах.', 'invalid_recognition', 502)
    if conflicts:
        warnings.append('На разных фото расходятся ответы на задания ' + ', '.join(task_numbers[i] for i in dict.fromkeys(conflicts)) + '. Сверьте страницы; вариант ответа не выбран автоматически.')
    if any(a['state'] == 'unclear' for a in answers):
        warnings.append('Есть неразборчивые ответы или отсутствующие номера. Проверьте полноту страниц.')
    for answer, task in zip(answers, assignment['worksheet']['tasks']):
        answer.update(hint(task['answer'], answer['text'], answer['state']))
        answer['score'] = answer['suggested_score']
        answer['comment'] = ''
    if not 1 <= len(paths) <= 5:
        fail('Неверное количество фотографий.', 'invalid_recognition', 502)
    for index, path in enumerate(paths):
        target = photo_path(review_id, index)
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, target)
    conn.execute("UPDATE reviews SET status='needs_review',answers=?,warnings=?,photo_count=?,revision=revision+1,updated_at=? WHERE id=?",
                 (json.dumps(answers, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), len(paths), timestamp(), review_id))
    audit(conn, owned(conn, owner, review_id), 'recognized')
    return {'review_id': review_id, 'assignment_id': assignment['id']}


def detail(conn, owner, review_id):
    row = owned(conn, owner, review_id)
    assignment = context(conn, owner, row['assignment_id'], row['student_id'])
    job = conn.execute('SELECT status,error FROM jobs WHERE id=? AND owner_id=?', (row['job_id'], owner)).fetchone()
    result = {k: row[k] for k in ('id', 'assignment_id', 'student_id', 'status', 'revision', 'comment', 'created_at', 'updated_at', 'confirmed_at')}
    result.update(student_code=class_store.student_code(row['student_id']), title=assignment['title'], class_name=assignment['class_name'],
                  edition_code=assignment['code'], answers=json.loads(row['answers']), warnings=json.loads(row['warnings']),
                  tasks=assignment['worksheet']['tasks'], photo_expires=row['photo_expires'],
                  photos=[f'/api/v2/reviews/{review_id}/photos/{i}' for i in range(row['photo_count'])] if row['photo_expires'] > time.time() else [],
                  job_status=job['status'] if job else None, error=job['error'] if job else None)
    draft = conn.execute('SELECT * FROM review_drafts WHERE review_id=?', (review_id,)).fetchone()
    result['draft'] = (dict(json.loads(draft['payload']), revision=draft['revision'], base_revision=draft['base_revision'],
                            updated_at=draft['updated_at'], stale=draft['base_revision'] != row['revision']) if draft else None)
    return result


def get_review(owner, review_id):
    with connection() as conn:
        return detail(conn, owner, review_id)


def editable(conn, owner, row, value, confirm=False):
    """Validate teacher input without applying it to the official result."""
    assignment = context(conn, owner, row['assignment_id'], row['student_id'])
    tasks, incoming = assignment['worksheet']['tasks'], value.get('answers')
    if not isinstance(incoming, list) or len(incoming) != len(tasks):
        fail('Проверьте ответы всех заданий.')
    previous = {a['task_id']: a for a in json.loads(row['answers'])}
    answers = []
    for task, item in zip(tasks, incoming):
        if not isinstance(item, dict) or item.get('task_id') != task['id']:
            fail('Порядок заданий изменён. Откройте проверку заново.')
        text, comment, score = item.get('text'), item.get('comment', ''), item.get('score')
        if not isinstance(text, str) or len(text) > 2000 or '\x00' in text or not isinstance(comment, str) or len(comment) > 500 or '\x00' in comment:
            fail('Ответ — до 2000 символов, комментарий — до 500.')
        if score is not None and (type(score) is not int or score not in (0, 1)):
            fail('За каждое задание можно поставить 0 или 1 балл.')
        if confirm and score is None:
            fail('Укажите баллы за каждое задание. Пропуск не равен нулю.', 'scores_incomplete', 400)
        answer = dict(previous[task['id']], text=text.strip(), comment=comment.strip(), score=score)
        answer['teacher_edited'] = bool(answer.get('teacher_edited')) or answer['text'] != previous[task['id']]['text']
        comparison_state = ('readable' if answer['text'] else 'blank') if answer['teacher_edited'] else answer['state']
        answer.update(hint(task['answer'], answer['text'], comparison_state))
        answers.append(answer)
    comment = value.get('comment', '')
    if not isinstance(comment, str) or len(comment) > 2000 or '\x00' in comment:
        fail('Комментарий к работе — до 2000 символов.')
    return {'answers': answers, 'comment': comment.strip()}


def check_revision(row, value):
    if type(value.get('revision')) is not int or value['revision'] != row['revision']:
        fail('Проверка изменена на другом устройстве. Откройте свежий результат.', 'revision_conflict', 409)
    if row['status'] not in ('needs_review', 'confirmed'):
        fail('Сначала дождитесь распознавания.', 'review_not_ready', 409)


def check_draft(conn, row, value):
    draft = conn.execute('SELECT * FROM review_drafts WHERE review_id=?', (row['id'],)).fetchone()
    expected = value.get('draft_revision')
    if expected != (draft['revision'] if draft else None) or (draft and draft['base_revision'] != row['revision']):
        fail('Черновик изменён в другой вкладке. Скачайте свои правки и откройте проверку заново.', 'draft_conflict', 409)
    return draft


def save_draft(owner, review_id, value):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = owned(conn, owner, review_id)
        check_revision(row, value)
        check_draft(conn, row, value)
        payload = editable(conn, owner, row, value)
        conn.execute('INSERT OR REPLACE INTO review_drafts VALUES(?,?,?,?,?)',
                     (review_id, row['revision'], uuid.uuid4().hex, json.dumps(payload, ensure_ascii=False), timestamp()))
        return detail(conn, owner, review_id)['draft']


def discard_draft(owner, review_id, value):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = owned(conn, owner, review_id)
        check_revision(row, value)
        check_draft(conn, row, value)
        conn.execute('DELETE FROM review_drafts WHERE review_id=?', (review_id,))


def update(owner, review_id, value):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = owned(conn, owner, review_id)
        check_revision(row, value)
        check_draft(conn, row, value)
        action = value.get('action')
        if action not in ('save', 'confirm') or (row['status'] == 'confirmed' and action != 'confirm'):
            fail('Исправление подтверждённого результата нужно подтвердить заново.')
        if action == 'confirm' and value.get('reviewed') is not True:
            fail('Сверьте фото, код ученика, версию и баллы перед подтверждением.', 'review_required', 400)
        payload = editable(conn, owner, row, value, confirm=action == 'confirm')
        now = timestamp()
        conn.execute('UPDATE reviews SET status=?,answers=?,comment=?,revision=revision+1,updated_at=?,confirmed_at=? WHERE id=?',
                     ('confirmed' if action == 'confirm' else 'needs_review', json.dumps(payload['answers'], ensure_ascii=False), payload['comment'], now,
                      now if action == 'confirm' else None, review_id))
        audit(conn, owned(conn, owner, review_id), action)
        conn.execute('DELETE FROM review_drafts WHERE review_id=?', (review_id,))
        return detail(conn, owner, review_id)


def remove(owner, review_id, revision, draft_revision=None):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = owned(conn, owner, review_id)
        if type(revision) is not int or row['revision'] != revision:
            fail('Проверка изменена. Обновите страницу.', 'revision_conflict', 409)
        check_draft(conn, row, {'draft_revision': draft_revision})
        if row['status'] in ('confirmed', 'processing'):
            fail('Подтверждённую или выполняющуюся проверку удалить нельзя.', 'review_locked', 409)
        conn.execute('DELETE FROM reviews WHERE id=?', (review_id,))
        # File deletion stays under the DB write reservation shared with backup.
        for i in range(row['photo_count']):
            photo_path(review_id, i).unlink(missing_ok=True)


def history(owner, review_id):
    with connection() as conn:
        owned(conn, owner, review_id)
        result, previous = [], None
        for row in conn.execute('SELECT * FROM review_history WHERE review_id=? ORDER BY revision', (review_id,)):
            snapshot = json.loads(row['snapshot'])
            changes = []
            if previous:
                before = {a['task_id']: a for a in json.loads(previous['answers'])}
                for number, answer in enumerate(json.loads(snapshot['answers']), 1):
                    fields = {key: {'before': before[answer['task_id']].get(key), 'after': answer.get(key)}
                              for key in ('text', 'score', 'comment') if before[answer['task_id']].get(key) != answer.get(key)}
                    if fields:
                        changes.append({'number': number, 'fields': fields})
            result.append({'revision': row['revision'], 'action': row['action'], 'created_at': row['created_at'], 'snapshot': snapshot,
                           'changes': changes, 'comment_change': ({'before': previous['comment'], 'after': snapshot['comment']}
                                                                 if previous and previous['comment'] != snapshot['comment'] else None)})
            previous = snapshot
        return result[::-1]


def summarize(students, maximum):
    """Official scores only; a missing or unconfirmed score is never zero."""
    scores = [s['score'] for s in students if s['status'] == 'confirmed' and s['score'] is not None]
    total = len(students)
    counts = {status: sum(s['status'] == status for s in students)
              for status in ('not_submitted', 'needs_review', 'processing', 'failed')}
    return dict(counts, total=total, submitted=total - counts['not_submitted'], confirmed=len(scores),
                pending_corrections=sum(s['status'] == 'confirmed' and s.get('has_draft', False) for s in students),
                average=round(sum(scores) / len(scores), 2) if scores else None,
                percent=round(100 * sum(scores) / (len(scores) * maximum), 1) if scores else None, maximum=maximum)


def report(owner, assignment_id, active_connection=None):
    with (nullcontext(active_connection) if active_connection is not None else connection()) as conn:
        if not conn.in_transaction:
            conn.execute('BEGIN')
        assignment = class_store.assignment_detail(conn, owner, assignment_id)
        reviews = {r['student_id']: r for r in conn.execute('SELECT * FROM reviews WHERE owner_id=? AND assignment_id=?', (owner, assignment_id))}
        draft_ids = {r[0] for r in conn.execute('SELECT d.review_id FROM review_drafts d JOIN reviews r ON r.id=d.review_id WHERE r.owner_id=? AND r.assignment_id=?', (owner, assignment_id))}
        tasks = assignment['worksheet']['tasks']
        students, confirmed = [], []
        for student in assignment['students']:
            row = reviews.get(student['id'])
            answers = json.loads(row['answers']) if row and row['status'] == 'confirmed' else None
            score = sum(a['score'] for a in answers) if answers is not None else None
            students.append(dict(student, review_id=row['id'] if row else None, status=row['status'] if row else 'not_submitted',
                                 score=score, maximum=len(tasks), confirmed_at=row['confirmed_at'] if row else None,
                                 task_scores=[a['score'] for a in answers] if answers is not None else [None] * len(tasks),
                                 has_draft=bool(row and row['id'] in draft_ids)))
            if score is not None:
                confirmed.append(json.loads(row['answers']))
        breakdown = []
        for task in tasks:
            correct = sum(next(a['score'] for a in answers if a['task_id'] == task['id']) for answers in confirmed)
            breakdown.append({'task_id': task['id'], 'question': task['question'], 'correct': correct, 'total': len(confirmed),
                              'percent': round(100 * correct / len(confirmed), 1) if confirmed else None})
        scores = [s['score'] for s in students if s['score'] is not None]
        summary = summarize(students, len(tasks))
        difficult = [i + 1 for i, t in enumerate(breakdown) if t['percent'] is not None and t['percent'] < 60]
        recommendation = ('Пока нет подтверждённых результатов. Завершите проверку, чтобы увидеть выводы.' if not scores else
                          'Повторите задания ' + ', '.join(map(str, difficult)) + ': менее 60% верных ответов среди подтверждённых работ.' if difficult else
                          'Во всех заданиях не менее 60% верных ответов среди подтверждённых работ. Просмотрите индивидуальные ошибки.')
        return {'assignment_id': assignment['id'], 'class_id': assignment['class_id'], 'class_name': assignment['class_name'],
                'title': assignment['title'], 'edition_code': assignment['code'], 'scheduled_date': assignment['scheduled_date'],
                'due_date': assignment['due_date'], 'generated_at': timestamp(), 'summary': summary, 'students': students, 'tasks': breakdown, 'recommendation': recommendation}


def csv_report(owner, assignment_id):
    from utils.report_export import assignment_csv
    return assignment_csv(report(owner, assignment_id))


def maintain(conn):
    conn.execute("""UPDATE reviews SET status='failed',updated_at=? WHERE status='processing' AND job_id IN
                    (SELECT id FROM jobs WHERE status IN ('failed','cancelled'))""", (timestamp(),))
    for row in conn.execute('SELECT id,photo_count FROM reviews WHERE photo_expires<? AND photo_count>0', (time.time(),)).fetchall():
        for i in range(row['photo_count']):
            photo_path(row['id'], i).unlink(missing_ok=True)
        conn.execute('UPDATE reviews SET photo_count=0 WHERE id=?', (row['id'],))
