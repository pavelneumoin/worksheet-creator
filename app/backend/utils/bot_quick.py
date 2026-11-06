"""Private chat workflow sharing the same owner-scoped materials and worker queue."""
from datetime import datetime, timezone, timedelta
import ipaddress
import json
from pathlib import Path
import socket
import tempfile
import time
from urllib.parse import urlsplit

import requests
from utils import class_store, job_store, latex, workspace_store
from utils.gigachat_client import AIServiceError
from utils.worksheet import validate_worksheet


def media_url(value):
    try:
        p=urlsplit(value);host=p.hostname or ''
        if (p.scheme!='https' or p.username or p.password or p.port not in (None,443)
            or not any(host==d or host.endswith('.'+d) for d in ('oneme.ru','okcdn.ru','max.ru'))):raise ValueError()
        addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError()
    except (ValueError,OSError,TypeError):
        raise AIServiceError('Не удалось безопасно получить файл MAX. Пришлите фото заново или загрузите его в кабинете.','invalid_media_url',400)
    return value


def download(media,folder,verify=True):
    paths=[];total=0
    # Fresh requests have no bot authorization, even on the official media CDN.
    for i,item in enumerate(media):
        with requests.get(media_url(item['url']),stream=True,timeout=(5,20),allow_redirects=False,verify=verify) as response:
            if response.status_code!=200:raise AIServiceError('Не удалось скачать вложение. Пришлите его повторно.','media_unavailable',400)
            path=folder/str(i);size=0
            with path.open('wb') as out:
                for part in response.iter_content(65536):
                    size+=len(part);total+=len(part)
                    if size>15*1024*1024 or total>40*1024*1024:raise AIServiceError('До 15 МБ на файл и 40 МБ на сообщение.','file_too_large',413)
                    out.write(part)
        with path.open('rb') as stream:head=stream.read(8)
        ext='.pdf' if head.startswith(b'%PDF-') else '.jpg' if head.startswith(b'\xff\xd8\xff') else '.png' if head.startswith(b'\x89PNG\r\n\x1a\n') else None
        if not ext:raise AIServiceError('Пришлите PNG, JPEG или один PDF без пароля.','invalid_image',415)
        target=path.with_suffix(ext);path.rename(target);paths.append(target)
    if any(p.suffix=='.pdf' for p in paths) and len(paths)!=1:raise AIServiceError('Пришлите один PDF отдельно от фотографий.','input_limit',400)
    return paths


def remember(user,job):
    with workspace_store.connection() as conn:
        conn.execute('INSERT OR IGNORE INTO bot_runs(job_id,user_id,created_at) VALUES(?,?,?)',(job['id'],user,time.time()))


def draft(owner):
    with workspace_store.connection() as conn:row=conn.execute('SELECT * FROM bot_drafts WHERE owner_id=?',(owner,)).fetchone()
    if not row:raise AIServiceError('Пришлите фото заданий или /лист и текст. После распознавания здесь появится черновик.','no_bot_draft',404)
    material=workspace_store.get_material(owner,row['material_id'])
    return material,row['revision']


def show_draft(client,user,material):
    sheet=material['worksheet'];owner=f'max:{user}'
    with workspace_store.connection() as conn:conn.execute('INSERT INTO bot_drafts VALUES(?,?,?) ON CONFLICT(owner_id) DO UPDATE SET material_id=excluded.material_id,revision=excluded.revision',(owner,material['id'],material['revision']))
    client.send(user,'Черновик сохранён в вашей личной библиотеке.\n'+sheet['title']+'\nПроверьте задания и ответы ниже. Для правок — /start; после проверки — /pdf.')
    for i,task in enumerate(sheet['tasks'],1):
        text=f"{i}. {task['question']}\nОтвет: {task['answer'] or 'не указан'}"+(f"\nПримечание: {task['note']}" if task['note'] else '')
        for offset in range(0,len(text),3500):client.send(user,text[offset:offset+3500])
    client.send(user,'Все задания проверены? Нажмите кнопку — соберу лист для учеников и ответы для вас.',buttons=[[{'type':'message','text':'Проверил, собрать PDF'}]])


def deliver_files(client,user,material):
    result=material.get('result')
    if not result:raise AIServiceError('PDF ещё не готов. Проверьте черновик /draft, затем отправьте /pdf.','no_bot_pdf',409)
    for key,title in (('pdf_url','Рабочий лист.pdf'),('keys_url','Ответы.pdf'),('teacher_url','Комплект учителя.pdf')):
        if result.get(key):
            name=Path(urlsplit(result[key]).path).name
            if not workspace_store.owns_file(f'max:{user}',name):raise AIServiceError('Файл недоступен.','artifact_missing',404)
            client.send_file(user,Path(latex.OUTPUT_DIR)/name,title)


def handle(client,item):
    user=item['user_id'];owner=f'max:{user}';action=item['action']
    with workspace_store.connection() as conn:conn.execute('INSERT INTO users VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET first_name=excluded.first_name',(owner,item['first_name'],'max'))
    if action=='quick_help':
        client.send(user,'Быстрый лист: пришлите до 10 фотографий одним сообщением, один PDF или /лист и текст заданий. Поддерживаются математика и физика. Черновик и ответы покажу прямо здесь, после вашей проверки пришлю PDF. Всё сохраняется в вашей личной библиотеке.\n\n/today — листы на сегодня\n/draft — последний черновик\n/files — повторить готовые PDF\n/start — открыть кабинет')
    elif action=='recognize':
        payload=json.loads(item.get('payload') or '{}') if isinstance(item.get('payload'),str) else item.get('payload',{})
        with tempfile.TemporaryDirectory(prefix='listok-bot-') as temporary:
            paths=download(payload.get('media',[]),Path(temporary),getattr(client,'verify',True))
            settings=validate_worksheet({'schema_version':1,'tasks':[{'question':'Настройки'}]})['settings']
            job,_=job_store.submit(owner,'recognize',item['id'],{'_bot_user':user,'text':payload.get('text',''),'subject':'physics' if 'физик' in payload.get('text','').lower() else 'math','settings':settings,'variant_count':1,'instructions':'Сохрани все условия исходных заданий. Не придумывай нечитаемые фрагменты.'},paths)
        remember(user,job);client.send(user,'Принял задания. Подготовлю черновик и ответы здесь; в личную библиотеку сохраню автоматически.')
    elif action=='draft':
        material,_=draft(owner);show_draft(client,user,material)
    elif action=='compile':
        material,revision=draft(owner)
        if revision!=material['revision']:raise AIServiceError('Лист изменился в кабинете. Сначала посмотрите актуальную версию: /draft.','revision_conflict',409)
        if material.get('result'):return deliver_files(client,user,material)
        job,_=job_store.submit(owner,'compile',item['id'],{'_bot_user':user,'worksheet':material['worksheet'],'material_id':material['id'],'revision':revision})
        remember(user,job);client.send(user,'Собираю PDF: лист ученика, ответы и полный комплект учителя.')
    elif action=='files':
        material,_=draft(owner);deliver_files(client,user,material)
    elif action=='today':
        today=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        works=[a for a in class_store.schedule(owner,today[:7]) if a['scheduled_date']==today and a['status']=='active']
        if not works:client.send(user,'На сегодня работ нет. Назначьте лист классу и выберите дату урока в расписании кабинета: /start.');return
        if len(works)>20:client.send(user,'На сегодня больше 20 работ. Все доступны в расписании кабинета: /start. Здесь отправлю первые 20.')
        for a in works[:20]:
            detail=class_store.get_assignment(owner,a['id']);client.send(user,a['class_name']+' · '+a['title'])
            name=Path(urlsplit(detail['result']['pdf_url']).path).name
            client.send_file(user,Path(latex.OUTPUT_DIR)/name,'Лист — '+a['class_name']+'.pdf')


def poll(client):
    with workspace_store.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT r.*,j.status AS job_status,j.kind,j.payload FROM bot_runs r JOIN jobs j ON j.id=r.job_id WHERE r.status='pending' AND j.status IN ('succeeded','failed','cancelled') ORDER BY r.created_at LIMIT 1").fetchone()
        if not row:return False
        item=dict(row);conn.execute("UPDATE bot_runs SET status='sending' WHERE job_id=?",(item['job_id'],))
    success=False
    try:
        job=job_store.get_job(f"max:{item['user_id']}",item['job_id'])
        if job['status']!='succeeded':client.send(item['user_id'],'Обработка не завершена. '+(job.get('error') or 'Запрос отменён.'))
        elif item['kind']=='recognize':show_draft(client,item['user_id'],workspace_store.get_material(f"max:{item['user_id']}",job['result']['material_id']))
        else:
            material=workspace_store.get_material(f"max:{item['user_id']}",json.loads(item['payload'])['material_id']);deliver_files(client,item['user_id'],material)
        success=True
    finally:
        with workspace_store.connection() as conn:conn.execute('UPDATE bot_runs SET status=? WHERE job_id=?',('sent' if success else 'failed',item['job_id']))
    return True
