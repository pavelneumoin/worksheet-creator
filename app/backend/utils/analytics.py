"""Confirmed score arithmetic, scoped to a teacher or consenting school members."""
from collections import defaultdict
import json
from utils import class_store,school_store,review_store,report_export
from utils.workspace_store import connection,timestamp

def metric(rows):
    confirmed=[r for r in rows if r['score'] is not None]
    points=sum(r['score'] for r in confirmed);maximum=sum(r['maximum'] for r in confirmed)
    return {'expected':len(rows),'confirmed':len(confirmed),'points':points,'maximum':maximum,
            'percent':round(100*points/maximum,1) if maximum else None,
            'coverage':round(100*len(confirmed)/len(rows),1) if rows else 0,
            'not_submitted':sum(r['status']=='not_submitted' for r in rows),
            'needs_review':sum(r['status'] in ('processing','needs_review','failed') for r in rows)}

def overview(user,filters,conn=None):
    from contextlib import nullcontext
    allowed={'scope','from_date','to_date','q','class_id','teacher_id'}
    if any(k not in allowed or not isinstance(v,str) or len(v)>160 for k,v in filters.items()) or filters.get('scope','teacher') not in ('teacher','school'):
        class_store.fail('Проверьте фильтры отчёта.','invalid_filters')
    start=class_store.validate_date(filters.get('from_date',''),'Начало периода')
    end=class_store.validate_date(filters.get('to_date',''),'Конец периода')
    if start and end and start>end:class_store.fail('Проверьте период отчёта.')
    q=class_store.label(filters.get('q',''),'Тема',160,required=False)
    school=filters.get('scope','teacher')=='school'
    with (nullcontext(conn) if conn is not None else connection()) as c:
        if not c.in_transaction:c.execute('BEGIN')
        title='Мои классы'
        if school:
            member=school_store.require_admin(c,user);title=member['name']
            owners=[r[0] for r in c.execute('SELECT user_id FROM school_members WHERE school_id=?',(member['school_id'],))]
        else:owners=[user]
        marks=','.join('?' for _ in owners)
        teachers=[dict(r) for r in c.execute(f'SELECT id,first_name FROM users WHERE id IN ({marks})',owners)]
        classes=[dict(r) for r in c.execute(f'SELECT id,name,owner_id FROM classrooms WHERE owner_id IN ({marks}) ORDER BY name',owners)]
        teacher=filters.get('teacher_id','');class_id=filters.get('class_id','')
        if teacher and teacher not in owners:class_store.fail('Учитель недоступен.','teacher_not_found',404)
        if class_id and class_id not in {x['id'] for x in classes}:class_store.fail('Класс недоступен.','class_not_found',404)
        work_rows=c.execute(f'''SELECT a.*,e.worksheet,e.code,u.first_name FROM assignments a JOIN editions e ON e.id=a.edition_id
              JOIN users u ON u.id=a.owner_id WHERE a.owner_id IN ({marks}) ORDER BY a.scheduled_date DESC,a.created_at DESC''',owners).fetchall()
        chosen=[]
        for row in work_rows:
            w=json.loads(row['worksheet'])
            topic=row['topic'] or w['title']
            if (teacher and row['owner_id']!=teacher) or (class_id and row['class_id']!=class_id):continue
            if start and (not row['scheduled_date'] or row['scheduled_date']<start):continue
            if end and (not row['scheduled_date'] or row['scheduled_date']>end):continue
            if q.casefold() not in (topic+' '+row['title']).casefold():continue
            chosen.append((row,w,topic))
        if len(chosen)>500:class_store.fail('Сузьте период или выберите класс: в отчёте не более 500 работ.','analytics_limit',400)
        entries=[];works=[];task_rows=[]
        for a,w,topic in chosen:
            reviews={r['student_id']:r for r in c.execute('SELECT * FROM reviews WHERE assignment_id=? AND owner_id=?',(a['id'],a['owner_id']))}
            rows=[];scores_by_task=defaultdict(list)
            for student in c.execute('SELECT student_id FROM assignment_students WHERE assignment_id=?',(a['id'],)):
                sid=student['student_id'];r=reviews.get(sid);answers=json.loads(r['answers']) if r and r['status']=='confirmed' else None
                score=sum(x['score'] for x in answers) if answers is not None else None
                item={'assignment_id':a['id'],'class_id':a['class_id'],'class_name':a['class_name'],'teacher':a['first_name'],
                      'topic':topic,'title':a['title'],'subject':w['subject'],'date':a['scheduled_date'],'student_code':class_store.student_code(sid),
                      'status':r['status'] if r else 'not_submitted','score':score,'maximum':len(w['tasks'])}
                rows.append(item)
                if answers is not None:
                    for x in answers:scores_by_task[x['task_id']].append(x['score'])
            entries.extend(rows)
            works.append({'id':a['id'],'class_id':a['class_id'],'class_name':a['class_name'],'teacher':a['first_name'],'title':a['title'],'topic':topic,
                          'date':a['scheduled_date'],'subject':w['subject'],'revision':a['revision'],**metric(rows)})
            for i,t in enumerate(w['tasks'],1):
                scores=scores_by_task[t['id']]
                task_rows.append({'class_name':a['class_name'],'topic':topic,'title':a['title'],'number':i,
                                  'correct':sum(s==1 for s in scores),'partial':sum(0<s<1 for s in scores),'points':sum(scores),'confirmed':len(scores),
                                  'percent':round(100*sum(scores)/len(scores),1) if scores else None})
        topics=[]
        for name,subject in sorted({(r['topic'],r['subject']) for r in entries}):
            group=[r for r in entries if r['topic']==name and r['subject']==subject]
            topics.append({'topic':name,'subject':subject,**metric(group)})
        groups=[{'id':c['id'],'name':c['name'],**metric([r for r in entries if r['class_id']==c['id']])} for c in classes if any(r['class_id']==c['id'] for r in entries)]
        totals=metric(entries);totals.update(assignments=len(works),classes=len(groups),students=len({(r['class_id'],r['student_code']) for r in entries}))
        return {'title':title,'scope':'school' if school else 'teacher','generated_at':timestamp(),'filters':dict(filters),
                'teachers':teachers,'available_classes':classes,'totals':totals,'classes':groups,'topics':topics,'works':works,'students':entries,'tasks':task_rows}

def csv_export(data):
    rows=[['Учитель','Класс','Тема','Работа','Дата','Код ученика','Статус','Баллы','Максимум']]
    rows.extend([[r['teacher'],r['class_name'],r['topic'],r['title'],r['date'],r['student_code'],report_export.LABELS[r['status']],report_export.decimal(r['score']),r['maximum']] for r in data['students']])
    return report_export.csv_text(rows)
