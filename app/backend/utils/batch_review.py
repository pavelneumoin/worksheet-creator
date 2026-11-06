"""One MFP PDF, explicit page-to-pupil mapping, then ordinary teacher reviews."""
import json
from pathlib import Path
import re
import shutil
import time
import uuid
from utils import db, class_store, review_store, grading_ai
from utils.workspace_store import connection, timestamp
from utils.gigachat_client import AIServiceError

MAX_PAGES = 40

def root():
    p=Path(db.DB_PATH).resolve().parent/'batch_photos';p.mkdir(exist_ok=True);return p

def photo(batch_id,index):
    if not re.fullmatch(r'[a-f0-9]{32}',batch_id) or type(index) is not int or not 0<=index<MAX_PAGES:
        review_store.fail('Страница не найдена.','batch_photo_not_found',404)
    p=root()/batch_id/f'{index}.jpg'
    if p.is_symlink() or p.resolve().parent != root()/batch_id:
        review_store.fail('Страница не найдена.','batch_photo_not_found',404)
    return p

def owned(conn,owner,batch_id):
    row=conn.execute('SELECT * FROM review_batches WHERE id=? AND owner_id=?',(batch_id,owner)).fetchone()
    if row is None: review_store.fail('Пачка сканов не найдена.','batch_not_found',404)
    return row

def enqueue(conn,owner,batch_id,payload,fingerprint):
    a=class_store.assignment_detail(conn,owner,payload.get('assignment_id'))
    if conn.execute('SELECT 1 FROM review_batches WHERE assignment_id=? AND fingerprint=?',(a['id'],fingerprint)).fetchone():
        review_store.fail('Этот PDF уже загружен. Откройте его в списке пачек.','batch_exists',409)
    if conn.execute('SELECT COUNT(*) FROM review_batches WHERE owner_id=? AND photo_count>0',(owner,)).fetchone()[0]>=20:
        review_store.fail('Сначала завершите текущие пачки. Сканы хранятся 7 дней.','batch_limit',409)
    conn.execute('INSERT INTO review_batches(id,owner_id,assignment_id,fingerprint,expires_at,created_at) VALUES(?,?,?,?,?,?)',
                 (batch_id,owner,a['id'],fingerprint,time.time()+review_store.PHOTO_RETENTION,timestamp()))
    return a

def recognize(tasks,paths,directory):
    from utils.ai_batch import write_result
    pages=[]
    for i,path in enumerate(paths):
        try:
            page=grading_ai.recognize(tasks,[path])
        except AIServiceError as exc:
            page={'answers':review_store.validate_recognition({'answers':[]},tasks),'student_code':'','edition_code':'','error':str(exc)[:300]}
            from utils import answer_markers
            page.update(answer_markers.read(path))
        pages.append(page)
        # Preserve paid work already completed if the process is interrupted.
        write_result(directory,{'batch_pages':pages,'photo_count':len(paths)})
    return {'batch_pages':pages,'photo_count':len(paths)}

def complete(conn,owner,batch_id,output,directory):
    row=owned(conn,owner,batch_id)
    a=class_store.assignment_detail(conn,owner,row['assignment_id'])
    count=output.get('photo_count');incoming=output.get('batch_pages')
    if type(count) is not int or not 1<=count<=MAX_PAGES or not isinstance(incoming,list) or not 1<=len(incoming)<=count:
        review_store.fail('Некорректный результат пачки.','invalid_batch',502)
    pages=[]
    codes={s['code']:s['id'] for s in a['students']}
    for i in range(count):
        item=incoming[i] if i<len(incoming) else {'answers':[],'error':'Обработка прервалась. Проверьте страницу вручную.'}
        answers=review_store.validate_recognition(item,a['worksheet']['tasks'])
        pupil=item.get('student_code','');edition=item.get('edition_code','')
        if not all(isinstance(v,str) and len(v)<=80 for v in (pupil,edition)): review_store.fail('Неверный код страницы.','invalid_batch',502)
        normalized=class_store.normalize_student_code(pupil)
        wrong_edition=bool(edition and edition.upper().replace(' ','')!=a['code'])
        assignment_code=item.get('assignment_code','')
        marker_warning=item.get('marker_warning','')
        if not all(isinstance(v,str) and len(v)<=300 for v in (assignment_code,marker_warning)):
            review_store.fail('Неверная метка страницы.','invalid_batch',502)
        wrong_assignment=bool(assignment_code and assignment_code!=a['id'])
        pages.append({'index':i,'answers':answers,'student_code':pupil,'edition_code':edition,
                      'assignment_code':assignment_code,'marker_warning':marker_warning,
                      'suggested_student_id':codes.get(normalized) if not (wrong_edition or wrong_assignment or marker_warning) else None,
                      'warning':marker_warning or ('QR другой назначенной работы: сверьте лист.' if wrong_assignment else 'Другой код версии: сверьте лист.' if wrong_edition else ''),
                      'error':str(item.get('error',''))[:300],'review_id':None})
        source=Path(directory)/f'page_{i+1}.jpg'
        if not source.is_file(): review_store.fail('Страница скана отсутствует.','batch_photo_missing',500)
        target=photo(batch_id,i);target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target)
    conn.execute('UPDATE review_batches SET pages=?,photo_count=?,revision=revision+1 WHERE id=?',
                 (json.dumps(pages,ensure_ascii=False),count,batch_id))
    return {'batch_id':batch_id,'assignment_id':a['id'],'pages':count}

def get(owner,batch_id):
    with connection() as conn:
        row=owned(conn,owner,batch_id);a=class_store.assignment_detail(conn,owner,row['assignment_id'])
        job=conn.execute('SELECT status,error FROM jobs WHERE id=? AND owner_id=?',(batch_id,owner)).fetchone()
        return {'id':batch_id,'assignment_id':a['id'],'title':a['title'],'class_name':a['class_name'],'revision':row['revision'],
                'students':a['students'],'pages':[{k:v for k,v in p.items() if k!='answers'} for p in json.loads(row['pages'])],
                'expired':row['expires_at']<=time.time(),'status':job['status'] if job else 'finished','error':job['error'] if job else None}

def list_batches(owner,assignment_id):
    with connection() as conn:
        class_store.assignment_detail(conn,owner,assignment_id)
        return [dict(r) for r in conn.execute('SELECT id,photo_count,created_at,expires_at FROM review_batches WHERE owner_id=? AND assignment_id=? ORDER BY created_at DESC',(owner,assignment_id))]

def attach(owner,batch_id,value):
    indices=value.get('pages')
    if not isinstance(indices,list) or not 1<=len(indices)<=5 or any(type(i) is not int or not 0<=i<MAX_PAGES for i in indices) or len(set(indices))!=len(indices):
        review_store.fail('Выберите от 1 до 5 разных страниц одного ученика.')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE');row=owned(conn,owner,batch_id)
        if type(value.get('revision')) is not int or row['revision']!=value['revision']: review_store.fail('Пачка изменилась. Обновите экран.','revision_conflict',409)
        if row['expires_at']<=time.time(): review_store.fail('Срок хранения сканов истёк.','batch_expired',410)
        pages=json.loads(row['pages'])
        if any(i>=len(pages) or pages[i]['review_id'] for i in indices): review_store.fail('Эти страницы уже использованы или ещё не готовы.','pages_used',409)
        a=review_store.context(conn,owner,row['assignment_id'],value.get('student_id'))
        paths=[photo(batch_id,i) for i in sorted(indices)]
        if any(not p.is_file() for p in paths): review_store.fail('Сканы больше не доступны.','batch_photo_missing',404)
        from utils.job_store import fingerprint
        review_id=uuid.uuid4().hex
        review_store.enqueue(conn,owner,review_id,{'assignment_id':a['id'],'student_id':value['student_id']},fingerprint('review_photo',{},paths))
        merged=grading_ai.merge_pages(a['worksheet']['tasks'],[pages[i] for i in sorted(indices)])
        result=review_store.complete(conn,owner,review_id,merged,paths)
        for i in indices:pages[i]['review_id']=review_id
        conn.execute('UPDATE review_batches SET pages=?,revision=revision+1 WHERE id=?',(json.dumps(pages,ensure_ascii=False),batch_id))
        return result

def maintain(conn):
    for row in conn.execute('SELECT id FROM review_batches WHERE photo_count>0 AND expires_at<?',(time.time(),)).fetchall():
        directory=(root()/row['id']).resolve()
        if directory.parent==root().resolve() and directory.is_dir():shutil.rmtree(directory)
        conn.execute("UPDATE review_batches SET photo_count=0,pages='[]' WHERE id=?",(row['id'],))
