"""Owner-bound, one-use chat actions. Scores stay drafts until explicit confirmation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import tempfile
import time
import uuid
from urllib.parse import urlencode, urlsplit

from PIL import Image
from utils import bot_login, class_store, job_store, latex, review_store, workspace_store
from utils.gigachat_client import AIServiceError


def fail(text):
    raise AIServiceError(text, 'bot_action_invalid', 409)


def owner(user): return f'max:{user}'


def button(user, text, kind, payload=None):
    raw = secrets.token_hex(16)
    with workspace_store.connection() as conn:
        conn.execute('DELETE FROM bot_actions WHERE expires_at<?', (time.time(),))
        conn.execute('INSERT INTO bot_actions VALUES(?,?,?,?,?)',
                     (bot_login.digest(raw), user, kind, json.dumps(payload or {},ensure_ascii=False), time.time()+3600))
    return {'type':'callback','text':text[:120],'payload':'lk:'+raw}


def take_action(user, raw):
    with workspace_store.connection() as conn:
        row = conn.execute('DELETE FROM bot_actions WHERE token_hash=? AND user_id=? AND expires_at>? RETURNING *',
                           (bot_login.digest(raw),user,time.time())).fetchone()
    if not row: fail('Кнопка уже использована или устарела. Откройте меню заново: /check, /next или /summary.')
    return row['kind'], json.loads(row['payload'])


def web_button(user, name, target, label='Открыть подробнее'):
    from utils.max_bot import app_origin
    token = bot_login.issue(user,name)
    return {'type':'link','text':label,'url':app_origin()+'/bot-login.html#'+urlencode({'token':token,'next':target})}


def choose_class(client,user,mode,media=None,offset=0):
    classes = [c for c in class_store.list_classes(owner(user)) if not c['archived']]
    if not classes:
        client.send(user,'Сначала создайте класс и назначьте ему готовый лист в кабинете: /start.'); return
    rows = [[button(user,c['name'],'choose_work',{'class_id':c['id'],'mode':mode,'media':media})] for c in classes[offset:offset+8]]
    if offset+8 < len(classes): rows.append([button(user,'Ещё классы','choose_class',{'mode':mode,'media':media,'offset':offset+8})])
    client.send(user,'Выберите класс:',buttons=rows)


def choose_work(client,user,data):
    classroom = class_store.get_class(owner(user),data['class_id'])
    works = [a for a in classroom['assignments'] if data['mode'] != 'check' or a['status']=='active']
    offset = data.get('offset',0)
    rows = [[button(user,a['title'][:75]+(' · '+a['scheduled_date'] if a['scheduled_date'] else ''),'selected',
                    {'assignment_id':a['id'],'mode':data['mode'],'media':data.get('media')})] for a in works[offset:offset+8]]
    if offset+8 < len(works): rows.append([button(user,'Ещё работы','choose_work',{**data,'offset':offset+8})])
    client.send(user,classroom['name']+' · выберите работу:' if works else 'У класса пока нет подходящих назначенных работ. Назначьте лист в кабинете: /start.',buttons=rows or None)


def current_context(user):
    with workspace_store.connection() as conn:
        conn.execute('DELETE FROM bot_context WHERE expires_at<?',(time.time(),))
        row = conn.execute('SELECT assignment_id FROM bot_context WHERE user_id=?',(user,)).fetchone()
        return row['assignment_id'] if row else None


def clear_context(user):
    with workspace_store.connection() as conn: conn.execute('DELETE FROM bot_context WHERE user_id=?',(user,))


def submit_batch(client,item,assignment_id,media):
    from utils.bot_quick import download
    user = item['user_id']; a = class_store.get_assignment(owner(user),assignment_id)
    with tempfile.TemporaryDirectory(prefix='listok-chat-scans-') as temporary:
        paths = download(media,Path(temporary),getattr(client,'verify',True))
        if len(paths)!=1 or paths[0].suffix!='.pdf': fail('Для пачки пришлите один PDF из МФУ, до 40 страниц и 15 МБ. Для обычного фото — /cancel, затем отправьте его.')
        job,_ = job_store.submit(owner(user),'batch_grade',item['id'],{'assignment_id':assignment_id,'_bot_user':user},paths)
    clear_context(user)
    client.send(user,f"Принял PDF: {a['class_name']} · {a['title']}. Распознаю страницы и сообщу о готовности. Баллы пока не выставляются.")
    return job


def needs_attention(answer):
    return answer.get('score') is None or (not answer.get('checked') and
        (answer.get('state')!='readable' or answer.get('comparison')!='matches' or answer.get('score')!=1 or answer.get('teacher_edited')))


def draft_body(review):
    draft = review.get('draft')
    if draft and draft.get('stale'): fail('Работа изменилась. Откройте кабинет и согласуйте черновик перед продолжением.')
    return {'revision':review['revision'],'draft_revision':draft['revision'] if draft else None,
            'comment':draft['comment'] if draft else review['comment'],
            'answers':[{k:a.get(k,False if k=='checked' else '') for k in ('task_id','text','score','comment','checked')}
                       for a in (draft['answers'] if draft else review['answers'])]}


def snapshot(review):
    return {'review_id':review['id'],'revision':review['revision'],
            'draft_revision':review['draft']['revision'] if review.get('draft') else None}


def ensure_snapshot(review,data):
    if snapshot(review) != {k:data.get(k) for k in ('review_id','revision','draft_revision')}:
        fail('Ответ изменён в кабинете или другой кнопкой. Баллы не перезаписаны. Откройте свежую проверку: /next.')


def excerpt(review,answer,path):
    if not review['photos']: return False
    source = next((s for s in answer.get('sources',[]) if type(s.get('photo_index')) is int and 0<=s['photo_index']<len(review['photos'])),{})
    index = source.get('photo_index',0)
    original = review_store.photo_path(review['id'],index)
    if not original.is_file(): return False
    with Image.open(original) as image:
        image = image.convert('RGB'); box = review_store.valid_box(source.get('box'))
        if box:
            w,h = image.size
            image = image.crop((max(0,int(box[0]*w/1000)-16),max(0,int(box[1]*h/1000)-16),
                                min(w,int(box[2]*w/1000)+16),min(h,int(box[3]*h/1000)+16)))
        image.thumbnail((1600,1600)); image.save(path,format='PNG')
    return True


def next_answer(client,user,name,assignment_id,after=None):
    report = review_store.report(owner(user),assignment_id)
    reviews = [review_store.get_review(owner(user),s['review_id']) for s in report['students'] if s['review_id'] and (s['status']=='needs_review' or s.get('has_draft'))]
    candidates = []
    for r in reviews:
        if r.get('draft') and r['draft'].get('stale'): continue
        answers = r['draft']['answers'] if r.get('draft') else r['answers']
        for i,a in enumerate(answers):
            if needs_attention(a): candidates.append((r,i,a))
    if not candidates:
        pending = [r for r in reviews if all(a.get('score') is not None for a in (r['draft']['answers'] if r.get('draft') else r['answers']))]
        if pending: return confirmation_preview(client,user,name,pending[0])
        client.send(user,'Сомнительных ответов в сопоставленных работах нет. Несопоставленные страницы откройте в кабинете; итог доступен по /summary.',
                    buttons=[[web_button(user,name,'report:'+assignment_id,'Результаты класса')]])
        return
    index = 0
    if after:
        index = next((i+1 for i,(r,n,a) in enumerate(candidates) if [r['id'],n]==after),0)%len(candidates)
    r,n,a = candidates[index]
    data = {**snapshot(r),'task_index':n,'assignment_id':assignment_id}
    text = (f"{r['class_name']} · {r['student_code']}\nЗадание {n+1} · осталось сомнительных: {len(candidates)}\n"
            + ('Ответ неразборчив или отсутствует номер.' if a['state']=='unclear' and not a.get('teacher_edited') else 'Поле пустое.' if not a['text'] else 'Прочитано: '+a['text'][:800])
            + '\nЭталон: '+r['tasks'][n]['answer'][:800]
            + '\n\nСверьте оригинал. Кнопки сохраняют черновик; итог подтверждается отдельно. Область скана может быть определена неточно.')
    rows = [[button(user,label,'score',{**data,'score':score}) for label,score in [('0',0),('½',.5),('1',1)]],
            [button(user,'Пропустить','next',{'assignment_id':assignment_id,'after':[r['id'],n]})],
            [web_button(user,name,'review:'+r['id'],'Исправить ответ / увеличить')]]
    with tempfile.TemporaryDirectory(prefix='listok-excerpt-') as directory:
        path=Path(directory)/'answer.png'
        if excerpt(r,a,path): client.send_image(user,path,text,buttons=rows)
        else: client.send(user,text+'\nСкан недоступен: срок хранения истёк.',buttons=[rows[1],rows[2]])


def confirmation_preview(client,user,name,review):
    body = draft_body(review)
    lines = [f"{review['class_name']} · {review['student_code']}",review['title'], 'Версия '+review['edition_code'],
             *review['warnings'], 'Баллы по заданиям: '+', '.join(f"{i}: {str(a['score']).replace('.',',')}" for i,a in enumerate(body['answers'],1)),
             f"Итого: {sum(a['score'] for a in body['answers'])} из {len(body['answers'])}.",
             'Подтвердите только после сверки оригинала, кода ученика, версии и всех баллов. Это добавит результат в статистику.']
    client.send(user,'\n'.join(lines)[:3900],buttons=[[button(user,'Сверил работу, подтвердить','confirm',{**snapshot(review),'assignment_id':review['assignment_id']})],
                                                  [web_button(user,name,'review:'+review['id'],'Сверить всю работу')]])


def lesson_summary(client,user,name,assignment_id):
    r = review_store.report(owner(user),assignment_id); s = r['summary']
    difficult = [str(i) for i,t in enumerate(r['tasks'],1) if t['percent'] is not None and t['percent']<70]
    text = (f"{r['class_name']} · {r['title']}\nПодтверждено: {s['confirmed']} из {s['total']}\n"
            f"Нужен учитель: {s['needs_review']} · Не сдали: {s['not_submitted']}\n"
            + ('Подтверждённых баллов пока нет.' if s['percent'] is None else f"Выполнение: {str(s['percent']).replace('.',',')}%\nДля разбора: "+(', '.join(difficult) or 'нет заданий ниже 70%')))
    client.send(user,text,buttons=[[button(user,'PDF отчёта','report_pdf',{'assignment_id':assignment_id}),button(user,'Повторить ошибки','repeat',{'assignment_id':assignment_id})],
                                  [button(user,'Продолжить проверку','next',{'assignment_id':assignment_id})],
                                  [web_button(user,name,'report:'+assignment_id,'Полный отчёт')]])


def repeat_preview(client,user,assignment_id):
    r=review_store.report(owner(user),assignment_id)
    difficult=[str(i) for i,t in enumerate(r['tasks'],1) if t['percent'] is not None and t['percent']<70][:6]
    if not difficult: client.send(user,'Нет подтверждённых заданий с выполнением ниже 70%. Сначала подтвердите результаты проверки.'); return
    client.send(user,'Подготовлю до 6 аналогичных заданий по номерам '+', '.join(difficult)+' для повторения темы «'+r['title']+'». Имена и ответы учеников в генерацию не передаются. Сначала покажу черновик, PDF — после вашей проверки.',
                buttons=[[button(user,'Создать черновик повторения','repeat_generate',{'assignment_id':assignment_id})]])


def repeat_generate(client,item,assignment_id):
    user=item['user_id']; r=review_store.report(owner(user),assignment_id)
    ids={t['task_id'] for t in r['tasks'] if t['percent'] is not None and t['percent']<70}
    a=class_store.get_assignment(owner(user),assignment_id); sheet=deepcopy(a['worksheet'])
    sheet['tasks']=[t for t in sheet['tasks'] if t['id'] in ids][:6]
    if not sheet['tasks']: fail('Результаты изменились: подтверждённых затруднений больше нет.')
    sheet['title']='Повторение · '+sheet['title'][:140]
    job,_=job_store.submit(owner(user),'variant',item['id'],{'worksheet':sheet,'difficulty':'same','variant_count':1,'_bot_user':user,
                           'instructions':'Короткий лист повторения по этим заданиям. Сохрани тему и число задач. Измени числовые данные и проверь новые ответы.'})
    client.send(user,'Готовлю лист повторения. Пришлю черновик с ответами для вашей проверки.')
    return job


def deliver_result_file(client,user,result,title):
    name=Path(urlsplit(result['pdf_url']).path).name
    if not workspace_store.owns_file(owner(user),name): fail('PDF больше недоступен. Сформируйте свежий файл.')
    client.send_file(user,Path(latex.OUTPUT_DIR)/name,title)


def today(client,user):
    date=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    works=[a for a in class_store.schedule(owner(user),date[:7]) if a['scheduled_date']==date and a['status']=='active']
    if not works: client.send(user,'На сегодня работ нет. Назначьте лист классу и дату урока в кабинете: /start.'); return
    client.send(user,f'Сегодня работ: {len(works)}. Отправляю листы и ключи. Недостающие бланки класса подготовлю по очереди.' + (' Здесь первые 20 работ; остальные — в расписании.' if len(works)>20 else ''))
    for a in works[:20]:
        detail=class_store.get_assignment(owner(user),a['id'])
        client.send(user,a['class_name']+' · '+a['title'])
        for key,title in [('pdf_url','Лист'),('keys_url','Ответы')]:
            if detail['result'].get(key): deliver_result_file(client,user,{'pdf_url':detail['result'][key]},title+' — '+a['class_name']+'.pdf')
        forms=next((f for f in detail['answer_forms'] if f['mode']=='class'),None)
        if forms: deliver_result_file(client,user,forms,'Бланки — '+a['class_name']+'.pdf')
        else:
            with workspace_store.connection() as conn:
                conn.execute('BEGIN IMMEDIATE')
                if not conn.execute("""SELECT 1 FROM bot_print_queue p WHERE user_id=? AND assignment_id=? AND
                                      (status='pending' OR EXISTS(SELECT 1 FROM jobs j WHERE j.request_key=p.id AND j.owner_id=? AND j.status IN ('queued','running')))""",(user,a['id'],owner(user))).fetchone():
                    conn.execute('INSERT INTO bot_print_queue(id,user_id,assignment_id,created_at) VALUES(?,?,?,?)',(uuid.uuid4().hex,user,a['id'],time.time()))


def poll_print_queue(client):
    with workspace_store.connection() as conn:
        # request_key is durable: crash after submit cannot create another compilation.
        row=conn.execute("""SELECT p.* FROM bot_print_queue p WHERE p.status='pending'
                            AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.owner_id='max:'||p.user_id AND j.status IN ('queued','running'))
                            ORDER BY p.created_at LIMIT 1""").fetchone()
    if not row:return False
    try:
        if row['created_at']<time.time()-86400: fail('Очередь печати устарела. Запросите свежий комплект: /today.')
        job_store.submit(owner(row['user_id']),'answer_forms',row['id'],{'assignment_id':row['assignment_id'],'mode':'class','_bot_user':row['user_id']})
    except AIServiceError as exc:
        if exc.code in ('worker_unavailable','owner_job_limit','queue_full'):return False
        with workspace_store.connection() as conn:conn.execute("UPDATE bot_print_queue SET status='failed' WHERE id=?",(row['id'],))
        client.send(row['user_id'],str(exc))
        return True
    with workspace_store.connection() as conn:conn.execute("UPDATE bot_print_queue SET status='submitted' WHERE id=?",(row['id'],))
    return True


def batch_ready(client,user,name,batch_id):
    from utils import batch_review
    b=batch_review.get(owner(user),batch_id)
    free=[p for p in b['pages'] if not p['review_id']]
    matched=[p for p in free if p.get('suggested_student_id') and p.get('assignment_code')==b['assignment_id'] and not p['warning']]
    codes=', '.join(dict.fromkeys(p['student_code'] for p in matched))
    text=f"Пачка готова: {b['class_name']} · {b['title']}\nСтраниц: {len(b['pages'])}. По QR сопоставлено: {len(matched)} из {len(free)} оставшихся.\n"
    rows=[]
    if matched:
        text+='Коды: '+codes+'\nСверьте коды перед прикреплением страниц. Это не подтверждает оценки.'
        rows.append([button(user,'Прикрепить страницы по QR','attach_qr',{'batch_id':batch_id,'revision':b['revision']})])
    rows.append([web_button(user,name,'batch:'+batch_id,'Открыть пачку / исправить коды')])
    client.send(user,text[:3900],buttons=rows)


def attach_qr(client,user,name,data):
    from utils import batch_review
    b=batch_review.get(owner(user),data['batch_id'])
    if b['revision']!=data['revision']: fail('Пачка изменилась. Откройте её в кабинете и проверьте сопоставление.')
    groups={}
    for p in b['pages']:
        if not p['review_id'] and p.get('suggested_student_id') and p.get('assignment_code')==b['assignment_id'] and not p['warning']:
            groups.setdefault(p['suggested_student_id'],[]).append(p['index'])
    used=0
    for student,indices in groups.items():
        if len(indices)>5: continue
        try: batch_review.attach(owner(user),b['id'],{'revision':b['revision'],'student_id':student,'pages':indices})
        except AIServiceError as exc:
            if exc.code in ('review_exists','duplicate_submission'):continue
            raise
        used+=len(indices);b=batch_review.get(owner(user),b['id'])
    client.send(user,f'Прикреплено страниц: {used}. Нераспознанные и повторные страницы проверьте в кабинете. Баллы требуют подтверждения.')
    next_answer(client,user,name,b['assignment_id'])


def handle(client,item):
    from utils import bot_quick
    user=item['user_id']; name=item['first_name']; action=item['action']
    data=json.loads(item.get('payload') or '{}') if isinstance(item.get('payload'),str) else item.get('payload',{})
    if action=='callback':
        try: client.call('POST','/answers',params={'callback_id':data['callback_id']},json={'notification':'Открываю…'})
        except Exception: pass # A failed spinner acknowledgement must not erase a valid action.
        action,data=take_action(user,data['token'])
    if action=='cancel': clear_context(user);client.send(user,'Ожидание сканов отменено. Фото снова создаёт рабочий лист; /check — начать проверку.');return
    if action=='today': return today(client,user)
    if action in ('check','review_next','summary','repeat') and not data.get('assignment_id'):
        return choose_class(client,user,{'review_next':'next'}.get(action,action))
    if action=='choose_class':return choose_class(client,user,data['mode'],data.get('media'),data.get('offset',0))
    if action=='choose_work':return choose_work(client,user,data)
    if action=='chat_media':
        assignment=current_context(user)
        if assignment:return submit_batch(client,item,assignment,data.get('media',[]))
        if any(m.get('type')=='file' for m in data.get('media',[])):
            client.send(user,'Как использовать файл?',buttons=[[button(user,'Создать рабочий лист','create_from_file',data)],
                                                             [button(user,'Проверить работы класса','choose_class',{'mode':'check','media':data.get('media',[])})]])
            return
        return bot_quick.handle(client,{**item,'action':'recognize'})
    if action=='create_from_file': return bot_quick.handle(client,{**item,'action':'recognize','payload':data})
    if action=='selected':
        class_store.get_assignment(owner(user),data['assignment_id'])
        action=data['mode']
    if action=='check':
        if data.get('media'):return submit_batch(client,item,data['assignment_id'],data['media'])
        a=class_store.get_assignment(owner(user),data['assignment_id'])
        with workspace_store.connection() as conn:conn.execute('INSERT OR REPLACE INTO bot_context VALUES(?,?,?)',(user,a['id'],time.time()+1800))
        client.send(user,f"Жду один PDF с работами: {a['class_name']} · {a['title']}. До 40 страниц, 15 МБ. Режим действует 30 минут; /cancel — отмена.")
    elif action=='next':next_answer(client,user,name,data['assignment_id'],data.get('after'))
    elif action=='score':
        r=review_store.get_review(owner(user),data['review_id']);ensure_snapshot(r,data)
        body=draft_body(r);body['answers'][data['task_index']].update(score=data['score'],checked=True)
        review_store.save_draft(owner(user),r['id'],body)
        next_answer(client,user,name,data['assignment_id'])
    elif action=='confirm':
        r=review_store.get_review(owner(user),data['review_id']);ensure_snapshot(r,data)
        body=draft_body(r);body.update(action='confirm',reviewed=True)
        review_store.update(owner(user),r['id'],body)
        client.send(user,'Работа подтверждена и вошла в статистику.')
        next_answer(client,user,name,data['assignment_id'])
    elif action=='summary':lesson_summary(client,user,name,data['assignment_id'])
    elif action=='report_pdf':
        job_store.submit(owner(user),'report_pdf',item['id'],{'assignment_id':data['assignment_id'],'_bot_user':user})
        client.send(user,'Готовлю PDF по подтверждённым результатам. Пришлю сюда после сборки.')
    elif action=='repeat':repeat_preview(client,user,data['assignment_id'])
    elif action=='repeat_generate':return repeat_generate(client,item,data['assignment_id'])
    elif action=='attach_qr':attach_qr(client,user,name,data)
    else:fail('Действие недоступно. Откройте меню заново: /help.')
