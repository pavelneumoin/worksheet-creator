"""A private synthetic workspace per signed-in owner, with real application workflows."""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import time
import uuid

from PIL import Image, ImageDraw, ImageFont

from utils import latex, review_store, batch_review, answer_markers
from utils.answer_check import hint
from utils.class_store import student_code
from utils.demo_catalog import sheets, ANSWERS
from utils.gigachat_client import AIServiceError
from utils.worksheet import edition_code
from utils.workspace_store import connection, timestamp

ASSETS = Path(__file__).resolve().parents[1] / 'assets/demo'
FONTS = ASSETS.parent / 'fonts/cmu'


def uid():
    return uuid.uuid4().hex


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def realm(owner):
    return ':'.join(owner.split(':')[:2]) + ':' if owner.startswith('demo:') else ''


def same_realm(left, right):
    return realm(left) == realm(right)


def scan(assignment, edition, pupil, title, answers):
    image = Image.new('RGB', (1000,1414), 'white')
    draw = ImageDraw.Draw(image)
    regular = ImageFont.truetype(str(FONTS/'cmunrm.otf'), 28)
    bold = ImageFont.truetype(str(FONTS/'cmunbx.otf'), 30)
    ink = ImageFont.truetype(str(FONTS/'cmunti.otf'), 36)
    draw.text((65,55),'ДЕМО / БЛАНК ОТВЕТОВ',font=bold,fill='#202a3d')
    draw.text((65,110),title,font=regular,fill='black')
    draw.text((65,170),'Код ученика: '+student_code(pupil),font=bold,fill='black')
    draw.text((65,220),'Версия работы: '+edition,font=regular,fill='black')
    marker=Image.open(io.BytesIO(answer_markers.png(assignment,edition,student_code(pupil)))).convert('RGB')
    image.paste(marker.resize((170,170)),(770,155))
    draw.text((65,340),'Учебный пример. Все ответы подготовлены заранее.',font=regular,fill='#687184')
    for i,text in enumerate(answers):
        y=440+i*110
        draw.text((65,y+10),str(i+1),font=bold,fill='black')
        draw.rectangle((120,y,920,y+70),outline='#b1b9c4',width=2)
        for x in range(160,920,40):draw.line((x,y,x,y+70),fill='#dbe0e8',width=1)
        fitted=ink
        for size in range(36,17,-1):
            fitted=ImageFont.truetype(str(FONTS/'cmunti.otf'),size)
            if fitted.getlength(text)<770:break
        draw.text((137,y+13),text,font=fitted,fill='#1c3b78')
    return image


def manifest(owner):
    with connection() as conn:
        row=conn.execute('SELECT manifest,real_owner FROM demo_spaces WHERE demo_owner=?',(owner,)).fetchone()
        if not row:
            raise AIServiceError('Откройте демо-кабинет.', 'demo_required', 404)
        data=json.loads(row['manifest'])
    if data.get('version',1)<2:
        ensure(row['real_owner'])
        return manifest(owner)
    return data


def ensure(real_owner):
    """One transaction and owner-bound identifiers; repeated clicks never duplicate data."""
    created_files=[]
    try:
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT demo_owner FROM demo_spaces WHERE real_owner=?',(real_owner,)).fetchone()
            if old:
                from utils.demo_advanced import upgrade
                upgrade(conn,old['demo_owner'],created_files)
                refresh_scans(conn,old['demo_owner'])
                return old['demo_owner']
            if not all((ASSETS/(key+'.pdf')).is_file() for key in sheets()):
                raise AIServiceError('Демо-материалы пока недоступны.', 'demo_unavailable', 503)
            ns=uid(); owner='demo:'+ns+':teacher'; colleague='demo:'+ns+':colleague'
            now=timestamp(); today=datetime.now(timezone(timedelta(hours=3))).date()
            for ident,name in [(owner,'Демо · учитель'),(colleague,'Демо · коллега')]:
                conn.execute('INSERT INTO users VALUES(?,?,?)',(ident,name,'demo'))
            school=uid()
            conn.execute('INSERT INTO schools VALUES(?,?,?,?)',(school,'Демонстрационная школа',owner,now))
            for ident,role in [(owner,'admin'),(colleague,'teacher')]:
                conn.execute('INSERT INTO school_members VALUES(?,?,?,?)',(school,ident,role,now))

            catalog=sheets(); materials={}; editions={}
            def material(key,who,compiled=True):
                mid=uid(); sheet=catalog[key]
                conn.execute('INSERT INTO materials VALUES(?,?,?,?,1,?,?)',(mid,who,encoded(sheet),'demo',now,now))
                conn.execute('INSERT INTO material_meta VALUES(?,?,0)',(mid,'Учебные примеры'))
                if not compiled:return mid,None
                aid=uid(); names={}
                for column,suffix in [('pdf',''),('answers','_keys'),('teacher','_teacher')]:
                    name=aid+suffix+'.pdf'; target=Path(latex.OUTPUT_DIR)/name
                    created_files.append(target);shutil.copyfile(ASSETS/(key+suffix+'.pdf'),target);names[column]=name
                conn.execute('INSERT INTO artifacts(id,owner_id,material_id,pdf,answers,teacher,created_at) VALUES(?,?,?,?,?,?,?)',
                             (aid,who,mid,names['pdf'],names['answers'],names['teacher'],now))
                conn.execute('INSERT INTO editions VALUES(?,?,?,?,?,?,?)',(aid,who,mid,encoded(sheet),edition_code(sheet),1,now))
                return mid,aid
            for key in catalog:materials[key],editions[key]=material(key,owner)
            draft,_=material('equations',owner,False)
            peer_material,peer_edition=material('physics',colleague)

            # The exchange feed is isolated to this demo's realm.
            for mid,key,who,author in [(materials['fractions'],'fractions',owner,'Демо · учитель'),
                                        (peer_material,'physics',colleague,'Демо · коллега')]:
                sheet=dict(catalog[key],teacher_name='');pid=uid();search=(sheet['title']+' '+author).casefold()
                conn.execute('INSERT INTO library_publications VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (pid,who,mid,encoded(sheet),sheet['title'],sheet['subject'],sheet['grade'],author,
                     'Учебный пример',search,None,now))
                voter=colleague if who==owner else owner
                conn.execute('INSERT INTO library_ratings VALUES(?,?,?,?)',(pid,voter,5 if who==owner else 4,now))

            classes=[]
            for n,(name,who) in enumerate([('6А · демо',owner),('7Б · демо',owner),('7В · демо',colleague)]):
                cid=uid();pupils=[]
                conn.execute('INSERT INTO classrooms(id,owner_id,name,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,who,name,now,now))
                for i in range(8):
                    sid=f'{n+1:02X}{i+1:08X}'+uid()[:22];pupils.append(sid)
                    conn.execute('INSERT INTO students(id,class_id,name,created_at) VALUES(?,?,?,?)',(sid,cid,student_code(sid),now))
                classes.append((cid,name,who,pupils))

            assignments=[];pending=[]
            specs=[(0,'fractions',-7,True),(1,'equations',-2,True),(0,'fractions',0,True),
                   (2,'physics',-1,True),(0,'fractions',0,False),(1,'equations',3,False)]
            for w,(ci,key,offset,scored) in enumerate(specs):
                cid,cname,who,pupils=classes[ci];aid=uid();sheet=catalog[key];code=edition_code(sheet)
                title=sheet['title']+(' · загрузка PDF' if w==4 else '')
                day=(today+timedelta(days=offset)).isoformat()
                edition=peer_edition if who==colleague else editions[key]
                conn.execute('''INSERT INTO assignments(id,owner_id,class_id,edition_id,class_name,title,due_date,
                    instructions,request_key,fingerprint,created_at,scheduled_date,topic) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (aid,who,cid,edition,cname,title,day,'Учебный пример',uid(),uid(),now,day,sheet['title']))
                conn.executemany('INSERT INTO assignment_students VALUES(?,?,?)',[(aid,sid,student_code(sid)) for sid in pupils])
                assignments.append(aid)
                if not scored:continue
                for index,sid in enumerate(pupils[:7]):
                    rid=uid();confirmed=index<6;texts=list(ANSWERS[key]);scores=[]
                    for j in range(len(texts)):
                        score=1 if (index+j+w)%4 else 0
                        if index==3 and j==1:score=.5
                        scores.append(score)
                        if score==0:texts[j]=str(7+j+index)
                    if not confirmed:texts[1]='?';scores[1]=None
                    image=scan(aid,code,sid,title,texts)
                    target=review_store.photo_path(rid,0);target.parent.mkdir(exist_ok=True)
                    created_files.append(target);image.save(target,'JPEG',quality=88)
                    answers=[]
                    for j,(task,text,score) in enumerate(zip(sheet['tasks'],texts,scores)):
                        state='unclear' if text=='?' else 'readable';text='' if state=='unclear' else text
                        answers.append(dict(task_id=task['id'],text=text,state=state,**hint(task['answer'],text,state),
                            score=score,checked=confirmed,comment='Частичный балл' if score==.5 else '',
                            sources=[dict(photo_index=0,box=[60,int((440+j*110)/1.414),
                                min(940,max(340,round(200+ImageFont.truetype(str(FONTS/'cmunti.otf'),36).getlength(text)))),
                                int((520+j*110)/1.414)])]))
                    warnings=[] if confirmed else ['Задание 2: проверьте ответ по скану.']
                    conn.execute('''INSERT INTO reviews(id,owner_id,assignment_id,student_id,job_id,fingerprint,status,
                         answers,warnings,comment,photo_count,photo_expires,created_at,updated_at,confirmed_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                         (rid,who,aid,sid,rid,uid(),'confirmed' if confirmed else 'needs_review',encoded(answers),encoded(warnings),
                          'Учебный результат',1,time.time()+review_store.PHOTO_RETENTION,now,now,now if confirmed else None))
                    review_store.audit(conn,review_store.owned(conn,who,rid),'demo_prepared')
                    if not confirmed and who==owner:pending.append(rid)

            # Ready-to-map page for the last pupil, with matching QR and real attach workflow.
            aid=assignments[2];sid=classes[0][3][7];code=edition_code(catalog['fractions']);bid=uid()
            answers=[dict(task_id=str(i+1),text=t,state='readable',box=[60,int((440+i*110)/1.414),340,int((520+i*110)/1.414)]) for i,t in enumerate(ANSWERS['fractions'])]
            page=dict(index=0,answers=answers,student_code=student_code(sid),edition_code=code,assignment_code=aid,
                      marker_warning='',suggested_student_id=sid,warning='',error='',review_id=None)
            conn.execute('INSERT INTO review_batches(id,owner_id,assignment_id,fingerprint,pages,photo_count,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)',
                         (bid,owner,aid,uid(),encoded([page]),1,time.time()+review_store.PHOTO_RETENTION,now))
            target=batch_review.photo(bid,0);target.parent.mkdir(exist_ok=True);created_files.append(target)
            scan(aid,code,sid,catalog['fractions']['title'],ANSWERS['fractions']).save(target,'JPEG',quality=88)

            # Download and upload this PDF into the separate, initially empty assignment.
            sample=uid();name=sample+'.pdf';target=Path(latex.OUTPUT_DIR)/name;created_files.append(target)
            images=[]
            for i,sid in enumerate(classes[0][3][:3]):
                texts=list(ANSWERS['fractions'])
                if i==1:texts[1]='18'
                if i==2:texts[2]=''
                images.append(scan(assignments[4],code,sid,catalog['fractions']['title'],texts))
            images[0].save(target,'PDF',save_all=True,append_images=images[1:],resolution=120)
            for image in images:image.close()
            conn.execute('INSERT INTO artifacts(id,owner_id,pdf,created_at) VALUES(?,?,?,?)',(sample,owner,name,now))
            data=dict(materials=materials,classes=[c[0] for c in classes[:2]],draft=draft,
                      assignment=assignments[2],upload_assignment=assignments[4],review=pending[-1],
                      batch=bid,sample_pdf=dict(artifact_id=sample,pdf_url='/api/generated/'+name),
                      created_at=now,version=1)
            conn.execute('INSERT INTO demo_spaces VALUES(?,?,?,?)',(real_owner,owner,encoded(data),now))
            from utils.demo_advanced import upgrade
            upgrade(conn,owner,created_files)
            return owner
    except Exception:
        for path in created_files:path.unlink(missing_ok=True)
        raise


def refresh_scans(conn, owner):
    """Rebuild only prepared synthetic scans after normal retention expires."""
    for row in conn.execute('''SELECT r.*,a.title,e.code FROM reviews r JOIN assignments a ON a.id=r.assignment_id
            JOIN editions e ON e.id=a.edition_id WHERE r.owner_id LIKE ? AND (r.comment='Учебный результат'
            OR (r.comment='Учебный результат · старшие классы' AND r.status='needs_review'))
            AND r.photo_expires<?''',(realm(owner)+'%',time.time())):
        target=review_store.photo_path(row['id'],0);target.parent.mkdir(exist_ok=True)
        if not target.exists():
            scan(row['assignment_id'],row['code'],row['student_id'],row['title'],
                 [a['text'] or '?' for a in json.loads(row['answers'])]).save(target,'JPEG',quality=88)
        conn.execute('UPDATE reviews SET photo_count=1,photo_expires=? WHERE id=?',
                     (time.time()+review_store.PHOTO_RETENTION,row['id']))
    info=json.loads(conn.execute('SELECT manifest FROM demo_spaces WHERE demo_owner=?',(owner,)).fetchone()[0])
    batch=conn.execute('SELECT * FROM review_batches WHERE id=? AND owner_id=? AND expires_at<?',
                       (info['batch'],owner,time.time())).fetchone()
    if batch:
        assignment=conn.execute('SELECT a.*,e.code FROM assignments a JOIN editions e ON e.id=a.edition_id WHERE a.id=?',
                                (batch['assignment_id'],)).fetchone()
        sid=conn.execute('SELECT student_id FROM assignment_students WHERE assignment_id=? ORDER BY name DESC LIMIT 1',
                         (assignment['id'],)).fetchone()[0]
        existing=conn.execute('SELECT id FROM reviews WHERE assignment_id=? AND student_id=?',(assignment['id'],sid)).fetchone()
        answers=[dict(task_id=str(i+1),text=t,state='readable',box=[60,int((440+i*110)/1.414),340,int((520+i*110)/1.414)])
                 for i,t in enumerate(ANSWERS['fractions'])]
        page=dict(index=0,answers=answers,student_code=student_code(sid),edition_code=assignment['code'],
                  assignment_code=assignment['id'],marker_warning='',suggested_student_id=sid,warning='',error='',
                  review_id=existing['id'] if existing else None)
        target=batch_review.photo(batch['id'],0);target.parent.mkdir(exist_ok=True)
        scan(assignment['id'],assignment['code'],sid,assignment['title'],ANSWERS['fractions']).save(target,'JPEG',quality=88)
        conn.execute('UPDATE review_batches SET pages=?,photo_count=1,expires_at=?,revision=revision+1 WHERE id=?',
                     (encoded([page]),time.time()+review_store.PHOTO_RETENTION,batch['id']))
