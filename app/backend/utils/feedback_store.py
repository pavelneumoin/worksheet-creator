"""Short, teacher-facing product feedback with one editable response per profile."""
import uuid
from utils.workspace_store import connection, timestamp
from utils.gigachat_client import AIServiceError

def _text(value, label, limit, required=False):
    value = '' if value is None else value
    if not isinstance(value, str):
        raise AIServiceError(f'{label}: нужен текст.', 'invalid_feedback', 400)
    value = value.strip()
    if required and not value:
        raise AIServiceError(f'Заполните поле «{label}».', 'invalid_feedback', 400)
    if len(value) > limit:
        raise AIServiceError(f'Поле «{label}» слишком длинное.', 'invalid_feedback', 400)
    return value

def save(owner, first_name, value):
    if not isinstance(value, dict):
        raise AIServiceError('Передайте отзыв в формате формы.', 'invalid_feedback', 400)
    stars = value.get('stars')
    if type(stars) is not int or not 1 <= stars <= 5:
        raise AIServiceError('Поставьте оценку от 1 до 5 звёзд.', 'invalid_feedback', 400)
    display_name = _text(value.get('display_name') or first_name or 'Учитель', 'Имя', 80, True)
    liked = _text(value.get('liked'), 'Что понравилось', 1200)
    inconvenient = _text(value.get('inconvenient'), 'Что неудобно', 1200)
    improve = _text(value.get('improve'), 'Что исправить', 1200)
    recommend = value.get('recommend', False)
    if type(recommend) is not bool:
        raise AIServiceError('Неверный ответ о рекомендации.', 'invalid_feedback', 400)
    now = timestamp()
    with connection() as conn:
        existing = conn.execute('SELECT id,created_at FROM feedback_entries WHERE owner_id=?', (owner,)).fetchone()
        ident = existing['id'] if existing else uuid.uuid4().hex
        created = existing['created_at'] if existing else now
        conn.execute('''INSERT INTO feedback_entries
            (id,owner_id,display_name,stars,liked,inconvenient,improve,recommend,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET
            display_name=excluded.display_name,stars=excluded.stars,liked=excluded.liked,
            inconvenient=excluded.inconvenient,improve=excluded.improve,recommend=excluded.recommend,
            updated_at=excluded.updated_at''',
            (ident, owner, display_name, stars, liked, inconvenient, improve, int(recommend), created, now))
        row = conn.execute('SELECT * FROM feedback_entries WHERE id=?', (ident,)).fetchone()
    return _row(row, True)

def _row(row, own=False):
    return {'id': row['id'], 'display_name': row['display_name'], 'stars': row['stars'],
            'liked': row['liked'], 'inconvenient': row['inconvenient'], 'improve': row['improve'],
            'recommend': bool(row['recommend']), 'created_at': row['created_at'],
            'updated_at': row['updated_at'], **({'mine': True} if own else {})}

def list_feedback(owner):
    with connection() as conn:
        rows = conn.execute('SELECT * FROM feedback_entries ORDER BY updated_at DESC,id DESC LIMIT 200').fetchall()
        total, average = conn.execute('SELECT COUNT(*),AVG(stars) FROM feedback_entries').fetchone()
        recommend = conn.execute('SELECT COUNT(*) FROM feedback_entries WHERE recommend=1').fetchone()[0]
        mine = conn.execute('SELECT * FROM feedback_entries WHERE owner_id=?', (owner,)).fetchone()
    return {'summary': {'count': total, 'average': round(average, 1) if average is not None else None,
                        'recommend_count': recommend},
            'feedback': [_row(row, row['owner_id'] == owner) for row in rows],
            'mine': _row(mine, True) if mine else None}
