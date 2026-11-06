"""An owner-only queue over existing recognition, with explicit QR mapping approval."""
from collections import Counter
import json
import time

from utils import batch_review, class_store, review_store
from utils.workspace_store import connection


def needs_attention(answer):
    if answer.get('score') is None:
        return True
    if answer.get('checked') is True:
        return False
    return candidate(answer)


def candidate(answer):
    return (answer.get('state') != 'readable' or answer.get('comparison') != 'matches'
            or answer.get('score') != 1 or answer.get('teacher_edited') is True)


def mapping(conn, owner, row, assignment, pages):
    proposals, blocked = [], []
    counts = Counter(p.get('suggested_student_id') for p in pages)
    existing = {r['student_id'] for r in conn.execute(
        'SELECT student_id FROM reviews WHERE owner_id=? AND assignment_id=?', (owner, assignment['id']))}
    for p in pages:
        if p.get('review_id'):
            continue
        student = p.get('suggested_student_id')
        reason = ''
        if row['expires_at'] <= time.time(): reason = 'Срок хранения скана истёк'
        elif p.get('warning') or p.get('marker_warning'): reason = 'Нужно сверить код и версию'
        elif not student or p.get('assignment_code') != assignment['id'] or p.get('edition_code') != assignment['code']:
            reason = 'Нужно сопоставить страницу вручную'
        elif counts[student] != 1: reason = 'Несколько страниц с одним кодом — выберите вместе вручную'
        elif student in existing: reason = 'Работа ученика уже существует — сверьте страницы'
        elif p.get('error'): reason = 'Ошибка распознавания — откройте страницу вручную'
        elif not batch_review.photo(row['id'],p['index']).is_file(): reason = 'Скан недоступен'
        item = {'page':p['index'],'student_id':student,'student_code':class_store.student_code(student) if student else p.get('student_code','')}
        if reason: blocked.append(dict(item,reason=reason))
        else: proposals.append(item)
    return proposals, blocked


def snapshot(conn, owner, batch_id):
    row=batch_review.owned(conn,owner,batch_id)
    assignment=class_store.assignment_detail(conn,owner,row['assignment_id'])
    pages=json.loads(row['pages'])
    proposals,blocked=mapping(conn,owner,row,assignment,pages)
    reviews,items=[],[]
    for review_id in dict.fromkeys(p.get('review_id') for p in pages if p.get('review_id')):
        saved=conn.execute('SELECT * FROM reviews WHERE id=? AND owner_id=? AND assignment_id=?',
                           (review_id,owner,assignment['id'])).fetchone()
        if saved is None:
            blocked.append({'page':next(p['index'] for p in pages if p.get('review_id')==review_id),
                            'reason':'Проверка недоступна — обновите сопоставление'})
            continue
        r=review_store.detail(conn,owner,review_id)
        draft=r['draft'];answers=(draft or r)['answers']
        confirmed=r['status']=='confirmed' and draft is None
        usable=r['status'] in ('needs_review','confirmed') and not (draft and draft['stale'])
        attention=sum(needs_attention(a) for a in answers) if not confirmed else 0
        ready=usable and not confirmed and attention==0 and all(a.get('score') is not None for a in answers)
        reviews.append({'id':review_id,'student_code':r['student_code'],'confirmed':confirmed,
                        'ready':ready,'attention':attention,'usable':usable,'has_photos':bool(r['photos'])})
        if confirmed or not usable:
            continue
        for number,a in enumerate(answers,1):
            if candidate(a):
                items.append({'review_id':review_id,'task_id':a['task_id'],'number':number,
                              'student_code':r['student_code'],'resolved':not needs_attention(a),
                              'reason':'empty' if a['state']=='blank' else 'unclear' if a['state']=='unclear' else 'compare'})
    return {'id':batch_id,'assignment_id':assignment['id'],'revision':row['revision'],
            'title':assignment['title'],'class_name':assignment['class_name'],'page_count':len(pages),
            'expired':row['expires_at']<=time.time(),'proposals':proposals,'blocked':blocked,
            'reviews':reviews,'items':items,'remaining':sum(not i['resolved'] for i in items),
            'resolved':sum(i['resolved'] for i in items),'confirmed':sum(r['confirmed'] for r in reviews),
            'ready':sum(r['ready'] for r in reviews)}


def get(owner,batch_id):
    with connection() as conn:
        return snapshot(conn,owner,batch_id)


def prepare(owner,batch_id,value):
    """Approve deterministic single-page QR matches; never grade or re-run OCR."""
    created=[]
    try:
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=batch_review.owned(conn,owner,batch_id)
            if value.get('mapping_reviewed') is not True:
                review_store.fail('Сверьте страницы и коды перед началом.', 'mapping_required',400)
            if type(value.get('revision')) is not int or row['revision']!=value['revision']:
                review_store.fail('Пачка изменилась. Обновите очередь.', 'revision_conflict',409)
            if row['expires_at']<=time.time():
                review_store.fail('Срок хранения сканов истёк.', 'batch_expired',410)
            a=class_store.assignment_detail(conn,owner,row['assignment_id'])
            pages=json.loads(row['pages'])
            proposals,_=mapping(conn,owner,row,a,pages)
            for p in proposals:
                batch_review.attach_pages(conn,owner,row,pages,p['student_id'],[p['page']],created)
            if proposals:
                conn.execute('UPDATE review_batches SET pages=?,revision=revision+1 WHERE id=?',
                             (json.dumps(pages,ensure_ascii=False),batch_id))
            return snapshot(conn,owner,batch_id)
    except Exception:
        for review_id in created:
            # Only files generated by this transaction; no unrelated scans can be removed.
            directory=review_store.photo_path(review_id,0).parent
            for i in range(5): review_store.photo_path(review_id,i).unlink(missing_ok=True)
            if directory.is_dir(): directory.rmdir()
        raise
