"""Explicitly published worksheet snapshots; private artifacts never leave their owner."""
import json
import uuid

from utils.gigachat_client import AIServiceError
from utils.worksheet import text_field, validate_worksheet
from utils.workspace_store import connection, material_row, missing, timestamp

PAGE_SIZE = 12


def publication_row(conn, owner, row, detail=False):
    if row is None:
        missing()
    rating = conn.execute('SELECT AVG(stars),COUNT(*) FROM library_ratings WHERE publication_id=?',
                          (row['id'],)).fetchone()
    mine = conn.execute('SELECT stars FROM library_ratings WHERE publication_id=? AND owner_id=?',
                        (row['id'], owner)).fetchone()
    copies = conn.execute('SELECT COUNT(*) FROM library_copies WHERE publication_id=?', (row['id'],)).fetchone()[0]
    worksheet = json.loads(row['worksheet'])
    result = {'id': row['id'], 'title': row['title'], 'subject': row['subject'], 'grade': row['grade'],
              'author': row['author'], 'description': row['description'], 'created': row['created_at'],
              'task_count': len(worksheet['tasks']), 'rating': round(rating[0], 2) if rating[0] else None,
              'rating_count': rating[1], 'my_rating': mine[0] if mine else None, 'copies': copies,
              'is_owner': row['owner_id'] == owner, 'origin': json.loads(row['origin']) if row['origin'] else None}
    if detail:
        result['worksheet'] = worksheet
    return result


def get_publication(owner, publication_id):
    with connection() as conn:
        return publication_row(conn, owner, conn.execute('SELECT * FROM library_publications WHERE id=?',
                                                         (publication_id,)).fetchone(), detail=True)


def list_publications(owner, query='', subject='', sort='rating', page=1):
    query = text_field(query, 'Поиск', 160).casefold()
    if subject not in ('', 'math', 'physics') or sort not in ('rating', 'new', 'copies', 'mine'):
        raise AIServiceError('Выберите предмет и порядок материалов.', 'invalid_filter', 400)
    if type(page) is not int or not 1 <= page <= 10000:
        raise AIServiceError('Неверная страница библиотеки.', 'invalid_page', 400)
    filters, params = ['1=1'], []
    if query:
        # instr treats %, _ and quotes literally, including Cyrillic casefold.
        filters.append('instr(p.search_text, ?) > 0'); params.append(query)
    if subject:
        filters.append('p.subject=?'); params.append(subject)
    if sort == 'mine':
        filters.append('p.owner_id=?'); params.append(owner)
    order = {'rating': 'COALESCE(r.average,0) DESC,COALESCE(r.votes,0) DESC,p.created_at DESC,p.id',
             'new': 'p.created_at DESC,p.id', 'mine': 'p.created_at DESC,p.id',
             'copies': 'COALESCE(c.copies,0) DESC,p.created_at DESC,p.id'}[sort]
    where = ' AND '.join(filters)
    with connection() as conn:
        total = conn.execute('SELECT COUNT(*) FROM library_publications p WHERE ' + where, params).fetchone()[0]
        rows = conn.execute('''SELECT p.* FROM library_publications p
            LEFT JOIN (SELECT publication_id,AVG(stars) average,COUNT(*) votes FROM library_ratings GROUP BY publication_id) r
                ON r.publication_id=p.id
            LEFT JOIN (SELECT publication_id,COUNT(*) copies FROM library_copies GROUP BY publication_id) c
                ON c.publication_id=p.id WHERE ''' + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
            (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
        return {'publications': [publication_row(conn, owner, row) for row in rows], 'total': total,
                'page': page, 'has_more': page * PAGE_SIZE < total}


def publish(owner, material_id, revision, author, description, reviewed):
    if reviewed is not True:
        raise AIServiceError('Проверьте условия и ответы и подтвердите публикацию.', 'review_required', 400)
    author = text_field(author, 'Имя автора', 80, True)
    description = text_field(description, 'Описание', 600)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        material = conn.execute('SELECT * FROM materials WHERE id=? AND owner_id=?', (material_id, owner)).fetchone()
        if material is None:
            missing()
        if type(revision) is not int or revision != material['revision']:
            raise AIServiceError('Лист изменился. Откройте свежую версию перед публикацией.', 'revision_conflict', 409)
        if conn.execute('SELECT 1 FROM library_publications WHERE material_id=?', (material_id,)).fetchone():
            raise AIServiceError('Лист уже в библиотеке. Снимите публикацию, чтобы поделиться новой версией.',
                                 'already_published', 409)
        worksheet = validate_worksheet(json.loads(material['worksheet']))
        # The public author is chosen explicitly; private print-header names are not published.
        worksheet['teacher_name'] = ''
        origin = conn.execute('SELECT author,title FROM material_origins WHERE material_id=?', (material_id,)).fetchone()
        search = ' '.join([worksheet['title'], worksheet['grade'], author, description,
                           *(t['question'] for t in worksheet['tasks'])]).casefold()
        publication_id = uuid.uuid4().hex
        conn.execute('INSERT INTO library_publications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                     (publication_id, owner, material_id, json.dumps(worksheet, ensure_ascii=False), worksheet['title'],
                      worksheet['subject'], worksheet['grade'], author, description, search,
                      json.dumps(dict(origin), ensure_ascii=False) if origin else None, timestamp()))
        return publication_row(conn, owner, conn.execute('SELECT * FROM library_publications WHERE id=?',
                                                         (publication_id,)).fetchone(), detail=True)


def withdraw(owner, publication_id):
    with connection() as conn:
        result = conn.execute('DELETE FROM library_publications WHERE id=? AND owner_id=?', (publication_id, owner))
        if not result.rowcount:
            missing()


def rate(owner, publication_id, stars):
    if type(stars) is not int or not 1 <= stars <= 5:
        raise AIServiceError('Выберите оценку от 1 до 5 звёзд.', 'invalid_rating', 400)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM library_publications WHERE id=?', (publication_id,)).fetchone()
        if row is None:
            missing()
        if row['owner_id'] == owner:
            raise AIServiceError('Свою публикацию оценивать нельзя.', 'own_rating', 403)
        conn.execute('''INSERT INTO library_ratings VALUES (?,?,?,?)
            ON CONFLICT(publication_id,owner_id) DO UPDATE SET stars=excluded.stars,updated_at=excluded.updated_at''',
                     (publication_id, owner, stars, timestamp()))
        return publication_row(conn, owner, row, detail=True)


def copy_to_materials(owner, publication_id):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM library_publications WHERE id=?', (publication_id,)).fetchone()
        if row is None:
            missing()
        if conn.execute('SELECT COUNT(*) FROM materials WHERE owner_id=?', (owner,)).fetchone()[0] >= 500:
            raise AIServiceError('Достигнут предел: 500 материалов. Удалите ненужные листы.', 'materials_limit', 409)
        material_id, now = uuid.uuid4().hex, timestamp()
        conn.execute('INSERT INTO materials VALUES (?,?,?,?,1,?,?)',
                     (material_id, owner, row['worksheet'], 'community', now, now))
        conn.execute('INSERT INTO material_origins VALUES (?,?,?,?)',
                     (material_id, publication_id, row['author'], row['title']))
        if row['owner_id'] != owner:
            conn.execute('INSERT OR IGNORE INTO library_copies VALUES (?,?)', (publication_id, owner))
        return material_row(conn, owner, conn.execute('SELECT * FROM materials WHERE id=?', (material_id,)).fetchone())
