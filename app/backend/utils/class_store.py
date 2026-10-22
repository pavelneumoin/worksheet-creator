"""Assignments retain their edition and roster; all writes are transactional."""
from datetime import date
import hashlib
import json
import re
import uuid

from utils.gigachat_client import AIServiceError
from utils.workspace_store import connection, timestamp, result_links


def fail(message, code='invalid_class', status=400):
    raise AIServiceError(message, code, status)


def student_code(student_id):
    # The full internal UUID remains the identity. The short code is scoped to a class.
    return 'У-' + student_id[:10].upper()


def student_row(row):
    return {'id': row['id'], 'code': student_code(row['id']),
            **({'archived': bool(row['archived'])} if 'archived' in row.keys() else {})}


def label(value, title, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        fail(f'{title}: введите текст до {limit} символов без переносов строк.')
    value = ' '.join(value.split())
    if required and not value:
        fail(f'{title}: заполните поле.')
    return value


def revision(row, value):
    if type(value) is not int or value != row['revision']:
        fail('Данные изменились на другом устройстве. Обновите класс и повторите действие.', 'revision_conflict', 409)


def owned_class(conn, owner, class_id, value=None, active=False):
    row = conn.execute('SELECT * FROM classrooms WHERE id=? AND owner_id=?', (class_id, owner)).fetchone()
    if row is None:
        fail('Класс не найден.', 'class_not_found', 404)
    if value is not None:
        revision(row, value.get('revision'))
    if active and row['archived']:
        fail('Сначала верните класс из архива.', 'class_archived', 409)
    return row


def touch(conn, class_id):
    conn.execute('UPDATE classrooms SET revision=revision+1,updated_at=? WHERE id=?', (timestamp(), class_id))


def class_row(conn, row):
    result = {k: row[k] for k in ('id', 'name', 'revision', 'created_at', 'updated_at')}
    result['archived'] = bool(row['archived'])
    result['student_count'] = conn.execute('SELECT COUNT(*) FROM students WHERE class_id=? AND archived=0', (row['id'],)).fetchone()[0]
    result['assignment_count'] = conn.execute("SELECT COUNT(*) FROM assignments WHERE class_id=? AND status='active'", (row['id'],)).fetchone()[0]
    return result


def class_detail(conn, owner, class_id):
    result = class_row(conn, owned_class(conn, owner, class_id))
    result['students'] = [student_row(r) for r in conn.execute(
        'SELECT id,archived FROM students WHERE class_id=? ORDER BY created_at,id', (class_id,))]
    result['students'].sort(key=lambda s: (s['archived'], s['code']))
    result['assignments'] = [assignment_row(conn, r) for r in conn.execute(
        '''SELECT a.*,e.code FROM assignments a JOIN editions e ON e.id=a.edition_id
           WHERE a.owner_id=? AND a.class_id=? ORDER BY a.created_at DESC''', (owner, class_id))]
    return result


def list_classes(owner):
    with connection() as conn:
        return [class_row(conn, r) for r in conn.execute('SELECT * FROM classrooms WHERE owner_id=? ORDER BY archived,updated_at DESC', (owner,))]


def get_class(owner, class_id):
    with connection() as conn:
        return class_detail(conn, owner, class_id)


def unique_class_name(conn, owner, name, exclude=None):
    for row in conn.execute('SELECT id,name FROM classrooms WHERE owner_id=?', (owner,)):
        if row['id'] != exclude and row['name'].casefold() == name.casefold():
            fail('Класс с таким названием уже есть, возможно, в архиве. Добавьте учебный год или уточните название.', 'duplicate_class', 409)


def create_class(owner, value):
    name = label(value.get('name'), 'Название класса', 60)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        unique_class_name(conn, owner, name)
        if conn.execute('SELECT COUNT(*) FROM classrooms WHERE owner_id=?', (owner,)).fetchone()[0] >= 100:
            fail('В кабинете можно хранить до 100 классов.', 'class_limit', 409)
        class_id, now = uuid.uuid4().hex, timestamp()
        conn.execute('INSERT INTO classrooms (id,owner_id,name,created_at,updated_at) VALUES (?,?,?,?,?)', (class_id, owner, name, now, now))
        return class_detail(conn, owner, class_id)


def update_class(owner, class_id, value):
    name = label(value.get('name'), 'Название класса', 60)
    if type(value.get('archived')) is not bool:
        fail('Укажите состояние класса.')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        owned_class(conn, owner, class_id, value)
        unique_class_name(conn, owner, name, class_id)
        conn.execute('UPDATE classrooms SET name=?,archived=? WHERE id=?', (name, int(value['archived']), class_id))
        touch(conn, class_id)
        return class_detail(conn, owner, class_id)


def add_students(owner, class_id, value):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        owned_class(conn, owner, class_id, value, active=True)
        if set(value) - {'revision', 'count'}:
            fail('ФИО не сохраняются. Укажите только количество учеников; таблицу соответствия заполните на своём устройстве.', 'student_names_disabled')
        amount = value.get('count')
        if type(amount) is not int or not 1 <= amount <= 100:
            fail('Добавьте от 1 до 100 учеников за один раз.')
        count = conn.execute('SELECT COUNT(*) FROM students WHERE class_id=?', (class_id,)).fetchone()[0]
        if count + amount > 200:
            fail('В одном классе можно хранить до 200 записей, включая архив.', 'student_limit', 409)
        now = timestamp()
        existing = {student_code(r['id']) for r in conn.execute('SELECT id FROM students WHERE class_id=?', (class_id,))}
        records = []
        while len(records) < amount:
            student_id = uuid.uuid4().hex
            code = student_code(student_id)
            if code not in existing:
                existing.add(code)
                records.append((student_id, class_id, code, now))
        conn.executemany('INSERT INTO students (id,class_id,name,created_at) VALUES (?,?,?,?)',
                         records)
        touch(conn, class_id)
        return class_detail(conn, owner, class_id)


def update_student(owner, class_id, student_id, value):
    if type(value.get('archived')) is not bool:
        fail('Укажите состояние ученика.')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        owned_class(conn, owner, class_id, value, active=True)
        row = conn.execute('SELECT id FROM students WHERE id=? AND class_id=?', (student_id, class_id)).fetchone()
        if row is None:
            fail('Ученик не найден в этом классе.', 'student_not_found', 404)
        if set(value) - {'revision', 'archived'}:
            fail('Код ученика постоянный. ФИО храните в своей таблице.', 'student_names_disabled')
        conn.execute('UPDATE students SET archived=? WHERE id=? AND class_id=?', (int(value['archived']), student_id, class_id))
        touch(conn, class_id)
        return class_detail(conn, owner, class_id)


def assignment_row(conn, row, detail=False):
    result = {k: row[k] for k in ('id', 'class_id', 'class_name', 'edition_id', 'title', 'due_date', 'scheduled_date', 'instructions', 'status', 'revision', 'created_at', 'code')}
    result['student_count'] = conn.execute('SELECT COUNT(*) FROM assignment_students WHERE assignment_id=?', (row['id'],)).fetchone()[0]
    if detail:
        result['worksheet'] = json.loads(row['worksheet'])
        result['result'] = result_links(dict(row, id=row['edition_id']))
        result['students'] = [student_row(r) for r in conn.execute('SELECT student_id AS id FROM assignment_students WHERE assignment_id=?', (row['id'],))]
        result['students'].sort(key=lambda s: s['code'])
    return result


def assignment_detail(conn, owner, assignment_id):
    row = conn.execute('''SELECT a.*,e.code,e.worksheet,f.pdf,f.answers,f.tex,f.marp
                          FROM assignments a JOIN editions e ON e.id=a.edition_id JOIN artifacts f ON f.id=e.id
                          WHERE a.id=? AND a.owner_id=?''', (assignment_id, owner)).fetchone()
    if row is None:
        fail('Назначенная работа не найдена.', 'assignment_not_found', 404)
    return assignment_row(conn, row, True)


def get_assignment(owner, assignment_id):
    with connection() as conn:
        return assignment_detail(conn, owner, assignment_id)


def validate_date(value, title):
    if not isinstance(value, str):
        fail(f'{title}: укажите дату или оставьте поле пустым.')
    if value:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            fail(f'{title}: укажите существующую дату в формате ГГГГ-ММ-ДД.')
    return value


def schedule(owner, month):
    if not isinstance(month, str) or not re.fullmatch(r'\d{4}-\d{2}', month):
        fail('Выберите месяц.', 'invalid_month')
    validate_date(month + '-01', 'Месяц')
    with connection() as conn:
        rows = conn.execute('''SELECT a.*,e.code FROM assignments a JOIN editions e ON e.id=a.edition_id
                               WHERE a.owner_id=? AND substr(a.scheduled_date,1,7)=?
                               ORDER BY a.scheduled_date,a.created_at''', (owner, month)).fetchall()
        return [assignment_row(conn, r) for r in rows]


def assign(owner, class_id, value):
    title = label(value.get('title'), 'Название работы', 160)
    instructions = value.get('instructions', '')
    if not isinstance(instructions, str) or len(instructions) > 2000 or any(ord(c) < 32 and c not in '\n\r\t' for c in instructions):
        fail('Комментарий должен быть текстом до 2000 символов.')
    due = validate_date(value.get('due_date', ''), 'Срок сдачи')
    scheduled = validate_date(value.get('scheduled_date', ''), 'Дата проведения')
    if due and scheduled and due < scheduled:
        fail('Срок сдачи не может быть раньше даты проведения.')
    key = value.get('request_key')
    edition_id = value.get('edition_id')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
        fail('Обновите страницу перед назначением работы.', 'invalid_request_key')
    if not isinstance(edition_id, str) or not re.fullmatch(r'[a-f0-9]{32}', edition_id):
        fail('Выберите готовую версию листа.', 'invalid_edition')
    payload = [class_id, value.get('revision'), edition_id, title, due, instructions.strip()]
    if scheduled:
        payload.append(scheduled)  # Preserve idempotency keys from the previous release.
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        previous = conn.execute('SELECT id,fingerprint FROM assignments WHERE owner_id=? AND request_key=?', (owner, key)).fetchone()
        if previous:
            if previous['fingerprint'] != fingerprint:
                fail('Этот запрос уже использован для другой работы. Откройте назначение заново.', 'assignment_key_conflict', 409)
            return assignment_detail(conn, owner, previous['id']), False
        classroom = owned_class(conn, owner, class_id, value, active=True)
        edition = conn.execute('SELECT id FROM editions WHERE id=? AND owner_id=? AND material_id IS NOT NULL', (edition_id, owner)).fetchone()
        if edition is None:
            fail('Сначала сохраните и соберите лист в своих материалах.', 'edition_not_found', 404)
        students = conn.execute('SELECT id,name FROM students WHERE class_id=? AND archived=0', (class_id,)).fetchall()
        if not students:
            fail('Сначала добавьте учеников в класс.', 'empty_class', 409)
        if conn.execute('SELECT COUNT(*) FROM assignments WHERE class_id=?', (class_id,)).fetchone()[0] >= 500:
            fail('В одном классе можно хранить до 500 назначенных работ.', 'assignment_limit', 409)
        assignment_id = uuid.uuid4().hex
        conn.execute('''INSERT INTO assignments (id,owner_id,class_id,edition_id,class_name,title,due_date,instructions,request_key,fingerprint,created_at,scheduled_date)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (assignment_id, owner, class_id, edition_id, classroom['name'], title, due, instructions.strip(), key, fingerprint, timestamp(), scheduled))
        conn.executemany('INSERT INTO assignment_students VALUES (?,?,?)', [(assignment_id, s['id'], student_code(s['id'])) for s in students])
        touch(conn, class_id)
        return assignment_detail(conn, owner, assignment_id), True


def update_assignment(owner, assignment_id, value):
    if value.get('status') not in ('active', 'closed'):
        fail('Выберите состояние работы.')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = assignment_detail(conn, owner, assignment_id)
        revision(row, value.get('revision'))
        owned_class(conn, owner, row['class_id'], active=value['status'] == 'active')
        conn.execute('UPDATE assignments SET status=?,revision=revision+1 WHERE id=? AND owner_id=?', (value['status'], assignment_id, owner))
        touch(conn, row['class_id'])
        return assignment_detail(conn, owner, assignment_id)
