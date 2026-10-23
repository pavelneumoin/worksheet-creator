"""One consistent class overview, with a separate denominator for every worksheet."""
from collections import defaultdict
import json

from utils import class_store, review_store
from utils.workspace_store import connection, timestamp


def filters(value):
    result = {key: value.get(key, '') for key in ('from_date', 'to_date', 'subject', 'status', 'student_id', 'q')}
    for key, title in (('from_date', 'Начало периода'), ('to_date', 'Конец периода')):
        class_store.validate_date(result[key], title)
    if result['from_date'] and result['to_date'] and result['from_date'] > result['to_date']:
        class_store.fail('Начало периода не может быть позже конца.')
    if result['subject'] not in ('', 'math', 'physics') or result['status'] not in ('', 'active', 'closed'):
        class_store.fail('Выберите предмет и состояние работы из списка.')
    result['q'] = class_store.label(result['q'], 'Тема или название', 160, required=False)
    if not isinstance(result['student_id'], str):
        class_store.fail('Выберите код ученика.')
    return result


def overview(owner, class_id, value):
    selected = filters(value)
    with connection() as conn:
        # All counts and rosters come from the same read snapshot, even if a
        # teacher confirms a review on another device while this response builds.
        conn.execute('BEGIN')
        classroom = class_store.owned_class(conn, owner, class_id)
        students = [class_store.student_row(row) for row in conn.execute(
            'SELECT id,archived FROM students WHERE class_id=? ORDER BY archived,id', (class_id,))]
        students.sort(key=lambda s: (s['archived'], s['code']))
        pupil = next((s for s in students if s['id'] == selected['student_id']), None)
        if selected['student_id'] and pupil is None:
            class_store.fail('Ученик не найден в этом классе.', 'student_not_found', 404)
        rows = conn.execute('''SELECT a.*,e.code,e.worksheet FROM assignments a JOIN editions e ON e.id=a.edition_id
                               WHERE a.owner_id=? AND a.class_id=?''', (owner, class_id)).fetchall()
        work_count = len(rows)
        chosen = []
        for row in rows:
            worksheet = json.loads(row['worksheet'])
            if selected['subject'] and worksheet['subject'] != selected['subject']:
                continue
            if selected['status'] and row['status'] != selected['status']:
                continue
            if selected['from_date'] and (not row['scheduled_date'] or row['scheduled_date'] < selected['from_date']):
                continue
            if selected['to_date'] and (not row['scheduled_date'] or row['scheduled_date'] > selected['to_date']):
                continue
            if selected['q'].casefold() not in (row['title'] + ' ' + worksheet['title']).casefold():
                continue
            chosen.append((row, worksheet))
        chosen.sort(key=lambda item: (bool(item[0]['scheduled_date']), item[0]['scheduled_date'], item[0]['created_at'], item[0]['id']), reverse=True)
        rosters, reviews = defaultdict(set), defaultdict(dict)
        if chosen:
            ids = [row['id'] for row, _ in chosen]
            slots = ','.join('?' for _ in ids)
            for row in conn.execute(f'SELECT assignment_id,student_id FROM assignment_students WHERE assignment_id IN ({slots})', ids):
                rosters[row['assignment_id']].add(row['student_id'])
            # Return only numerical official scores from SQLite, never answer
            # transcriptions, answer keys, photos or private teacher comments.
            for row in conn.execute(f'''SELECT r.id,r.assignment_id,r.student_id,r.status,r.confirmed_at,
                    CASE WHEN r.status='confirmed' THEN
                        (SELECT SUM(json_extract(value,'$.score')) FROM json_each(r.answers)) END AS score,
                    EXISTS(SELECT 1 FROM review_drafts d WHERE d.review_id=r.id) AS has_draft
                    FROM reviews r WHERE r.owner_id=? AND r.assignment_id IN ({slots})''', [owner, *ids]):
                reviews[row['assignment_id']][row['student_id']] = dict(row)
        works = []
        for row, worksheet in chosen:
            members = rosters[row['id']]
            results = reviews[row['id']]
            scores = [results.get(member, {'status': 'not_submitted', 'score': None}) for member in members]
            summary = review_store.summarize(scores, len(worksheet['tasks']))
            individual = None
            if pupil:
                result = results.get(pupil['id'])
                individual = {'status': ('not_assigned' if pupil['id'] not in members else
                                         result['status'] if result else 'not_submitted'),
                              'score': result['score'] if result else None,
                              'review_id': result['id'] if result else None,
                              'has_draft': bool(result and result['has_draft'])}
            works.append({'assignment_id': row['id'], 'title': row['title'], 'topic': worksheet['title'],
                          'subject': worksheet['subject'], 'edition_code': row['code'], 'status': row['status'],
                          'scheduled_date': row['scheduled_date'], 'due_date': row['due_date'],
                          'summary': summary, 'student_result': individual})
        # These are counts of assignments/reviews, not unique pupils and not a
        # pooled achievement score across worksheets of different complexity.
        totals = {key: sum(w['summary'][key] for w in works) for key in
                  ('total', 'submitted', 'confirmed', 'not_submitted', 'needs_review', 'processing', 'failed', 'pending_corrections')}
        totals.update(works=len(works), undated=sum(not w['scheduled_date'] for w in works))
        return {'class_id': class_id, 'class_name': classroom['name'], 'archived': bool(classroom['archived']),
                'generated_at': timestamp(), 'filters': selected, 'available_work_count': work_count,
                'students': students, 'selected_student': pupil, 'works': works, 'totals': totals}
