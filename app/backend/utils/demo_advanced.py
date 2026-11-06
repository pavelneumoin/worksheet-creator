"""Additive demo upgrade: preserve earlier demo edits, add senior classes and pupil workflow."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import shutil
import time
import uuid
from utils import latex, review_store, student_store
from utils.answer_check import hint
from utils.class_store import student_code
from utils.demo_catalog import sheets,ANSWERS
from utils.worksheet import edition_code
from utils.workspace_store import timestamp

def upgrade(conn,owner,created_files):
    from utils.demo_space import ASSETS,scan,realm
    row=conn.execute('SELECT * FROM demo_spaces WHERE demo_owner=?',(owner,)).fetchone()
    data=json.loads(row['manifest'])
    if data.get('version',1)>=2:return
    now=timestamp();today=datetime.now(timezone(timedelta(hours=3))).date();catalog=sheets()
    colleague=realm(owner)+'colleague'
    school=conn.execute('SELECT school_id FROM school_members WHERE user_id=?',(owner,)).fetchone()[0]
    conn.execute("UPDATE users SET first_name='Демо · заместитель директора' WHERE id=?",(owner,))
    conn.execute("UPDATE users SET first_name='Демо · учитель физики' WHERE id=?",(colleague,))
    # Class rosters can grow, while historical assignment rosters remain immutable.
    for c in conn.execute('SELECT id FROM classrooms WHERE owner_id IN (?,?)',(owner,colleague)).fetchall():
        count=conn.execute('SELECT count(*) FROM students WHERE class_id=?',(c['id'],)).fetchone()[0]
        for _ in range(count,30):
            sid=uuid.uuid4().hex;conn.execute('INSERT INTO students(id,class_id,name,created_at) VALUES(?,?,?,?)',(sid,c['id'],student_code(sid),now))
    advanced=[]
    for index,(key,name,who) in enumerate([('trigonometry','11А · демо',owner),('logarithms','11Б · демо',owner),('physics_advanced','10В · демо',colleague)]):
        sheet=catalog[key];mid=data['materials'].get(key)
        artifact=conn.execute('SELECT id FROM artifacts WHERE material_id=? AND owner_id=?',(mid,owner)).fetchone() if mid and who==owner else None
        if not artifact:
            mid=uuid.uuid4().hex;eid=uuid.uuid4().hex
            conn.execute('INSERT INTO materials VALUES(?,?,?,?,1,?,?)',(mid,who,json.dumps(sheet,ensure_ascii=False),'demo',now,now))
            conn.execute('INSERT INTO material_meta VALUES(?,?,0)',(mid,'Старшие классы · демо'))
            names={}
            for field,suffix in [('pdf',''),('answers','_keys'),('teacher','_teacher'),('answer_form','_answer_form')]:
                name_file=eid+suffix+'.pdf';target=Path(latex.OUTPUT_DIR)/name_file;created_files.append(target);shutil.copyfile(ASSETS/(key+suffix+'.pdf'),target);names[field]=name_file
            conn.execute('INSERT INTO artifacts(id,owner_id,material_id,pdf,answers,teacher,answer_form,created_at) VALUES(?,?,?,?,?,?,?,?)',(eid,who,mid,names['pdf'],names['answers'],names['teacher'],names['answer_form'],now))
            conn.execute('INSERT INTO editions VALUES(?,?,?,?,?,?,?)',(eid,who,mid,json.dumps(sheet,ensure_ascii=False),edition_code(sheet),1,now))
            if who==owner:data['materials'][key]=mid
        else:eid=artifact['id']
        cid=uuid.uuid4().hex;aid=uuid.uuid4().hex
        conn.execute('INSERT INTO classrooms(id,owner_id,name,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,who,name,now,now))
        pupils=[]
        for _ in range(30):
            sid=uuid.uuid4().hex;pupils.append(sid);conn.execute('INSERT INTO students(id,class_id,name,created_at) VALUES(?,?,?,?)',(sid,cid,student_code(sid),now))
        day=(today-timedelta(days=index)).isoformat()
        conn.execute('''INSERT INTO assignments(id,owner_id,class_id,edition_id,class_name,title,due_date,instructions,request_key,fingerprint,created_at,scheduled_date,topic)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(aid,who,cid,eid,name,sheet['title'],day,'Покажите ход решения. Учебный пример.',uuid.uuid4().hex,uuid.uuid4().hex,now,day,sheet['title']))
        conn.executemany('INSERT INTO assignment_students VALUES(?,?,?)',[(aid,sid,student_code(sid)) for sid in pupils])
        reviews=[]
        for i,sid in enumerate(pupils[:27]):
            rid=uuid.uuid4().hex;confirmed=i<24;answers=[]
            for j,t in enumerate(sheet['tasks']):
                score=1 if (i+j+index)%5 else .5
                if (i+j)%11==0:score=0
                if not confirmed and j==1:score=None
                text=ANSWERS[key][j] if score==1 else ('?' if score is None else str(3+i+j))
                answers.append(dict(task_id=t['id'],text='' if score is None else text,state='unclear' if score is None else 'readable',**hint(t['answer'],text,'readable' if score is not None else 'unclear'),score=score,checked=confirmed,comment='Проверьте ограничения и вычисления.' if score!=1 else ''))
            count=0
            if not confirmed:
                target=review_store.photo_path(rid,0);target.parent.mkdir(exist_ok=True);created_files.append(target)
                scan(aid,edition_code(sheet),sid,sheet['title'],[a['text'] or '?' for a in answers]).save(target,'JPEG',quality=88);count=1
            conn.execute('''INSERT INTO reviews(id,owner_id,assignment_id,student_id,job_id,fingerprint,status,answers,warnings,comment,photo_count,photo_expires,created_at,updated_at,confirmed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(rid,who,aid,sid,rid,uuid.uuid4().hex,'confirmed' if confirmed else 'needs_review',json.dumps(answers,ensure_ascii=False),'[]','Учебный результат · старшие классы',count,time.time()+review_store.PHOTO_RETENTION,now,now,now if confirmed else None))
            review_store.audit(conn,review_store.owned(conn,who,rid),'demo_prepared');reviews.append(rid)
        advanced.append({'class_id':cid,'assignment_id':aid,'owner':who,'students':pupils,'reviews':reviews,'sheet':sheet,'key':key})
        if who==owner:data['classes'].append(cid)
    # Two authentic UI paths in a private demo: teacher inbox and the pupil's own portal.
    pupil=realm(owner)+'pupil';conn.execute('INSERT OR IGNORE INTO users VALUES(?,?,?)',(pupil,'Демо · ученик','demo'))
    for work,user in [(advanced[0],pupil),(advanced[2],owner)]:
        sid=work['students'][0];conn.execute('INSERT INTO student_links VALUES(?,?,?)',(sid,user,now))
        for number,status in ([(1,'returned'),(2,'needs_review')] if user==pupil else [(1,'returned')]):
            attempt=uuid.uuid4().hex;target=student_store.folder(attempt);target.mkdir(exist_ok=True);created_files.append(target/'0.jpg')
            scan(work['assignment_id'],edition_code(work['sheet']),sid,work['sheet']['title'],ANSWERS[work['key']]).save(target/'0.jpg','JPEG',quality=88)
            base=review_store.owned(conn,work['owner'],work['reviews'][0]);answers=json.loads(base['answers'])
            for answer in answers:answer['checked']=False
            conn.execute('''INSERT INTO student_attempts(id,owner_id,user_id,assignment_id,student_id,number,request_key,fingerprint,files,expires_at,status,answers,feedback,review_id,base_revision,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(attempt,work['owner'],user,work['assignment_id'],sid,number,uuid.uuid4().hex,uuid.uuid4().hex,'["0.jpg"]',time.time()+student_store.RETENTION,status,json.dumps(answers,ensure_ascii=False),'Проверьте ограничения и поясните расчёт. Можно прислать исправление.',base['id'],base['revision'],now,now))
            if user==pupil and number==2:data['student_attempt']=attempt
        if user==owner:data['student_assignment']=work['assignment_id']
    data['advanced_assignments']=[w['assignment_id'] for w in advanced]
    # Attach a blank answer form to old prepared editions without changing their contents.
    for key,mid in data['materials'].items():
        for art in conn.execute('SELECT id FROM artifacts WHERE material_id=? AND answer_form IS NULL',(mid,)).fetchall():
            source=ASSETS/(key+'_answer_form.pdf')
            if source.is_file():
                name=art['id']+'_answer_form.pdf';target=Path(latex.OUTPUT_DIR)/name;created_files.append(target);shutil.copyfile(source,target);conn.execute('UPDATE artifacts SET answer_form=? WHERE id=?',(name,art['id']))
    data['version']=2
    conn.execute('UPDATE demo_spaces SET manifest=? WHERE demo_owner=?',(json.dumps(data,ensure_ascii=False),owner))
