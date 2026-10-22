"""Real SQLite/API checks for rosters, assignment snapshots and isolation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
import uuid

import test_personal as personal
import test_cabinet_storage as cabinet
from utils import backup, class_store, db, workspace_store


class ClassTests(unittest.TestCase):
    setUp = personal.PersonalTests.setUp
    call = personal.PersonalTests.call
    signed = personal.PersonalTests.signed
    login = personal.PersonalTests.login
    create = personal.PersonalTests.create
    compiled = cabinet.CabinetTests.compiled

    def classroom(self, name='8А', names=None, client=None):
        client = client or self.client
        r = self.call(client, 'post', '/api/v2/classes', json={'name':name})
        self.assertEqual(r.status_code, 201, r.json)
        c = r.json['classroom']
        if names is not None:
            r = self.call(client, 'post', f"/api/v2/classes/{c['id']}/students", json={'count':len(names),'revision':c['revision']})
            self.assertEqual(r.status_code, 201, r.json)
            c = r.json['classroom']
        return c

    def assignment(self, c=None):
        c = c or self.classroom(names=['Ученик А', 'Ученик Б'])
        material, edition = self.compiled()
        payload = {'revision':c['revision'], 'edition_id':edition, 'title':'Проверка уравнений',
                   'due_date':'2026-11-06', 'instructions':'Запишите решение.', 'request_key':uuid.uuid4().hex}
        r = self.call(self.client, 'post', f"/api/v2/classes/{c['id']}/assignments", json=payload)
        self.assertEqual(r.status_code, 201, r.json)
        return c, material, r.json['assignment'], payload

    def test_all_class_routes_require_session_and_csrf(self):
        c = self.classroom(names=['Ученик'])
        for method, url, body in [('get','/api/v2/classes',None), ('get',f"/api/v2/classes/{c['id']}",None),
                                  ('post','/api/v2/classes',{'name':'9А'})]:
            self.assertEqual(self.call(self.anon,method,url,json=body).status_code,401)
        self.assertEqual(self.call(self.client,'post','/api/v2/classes',json={'name':'9А'},headers={'X-CSRF-Token':'wrong'}).status_code,403)

    def test_classes_students_and_assignments_are_isolated(self):
        c,m,a,payload = self.assignment()
        base = f"/api/v2/classes/{c['id']}"
        requests = [('get',base,None),('put',base,{'name':'9А','archived':False,'revision':3}),
                    ('post',base+'/students',{'names':['Чужой'],'revision':3}),
                    ('put',base+'/students/'+c['students'][0]['id'],{'name':'Чужой','archived':True,'revision':3}),
                    ('post',base+'/assignments',dict(payload,request_key=uuid.uuid4().hex)),
                    ('get','/api/v2/assignments/'+a['id'],None),
                    ('put','/api/v2/assignments/'+a['id'],{'status':'closed','revision':1})]
        for method,url,body in requests:
            with self.subTest(url=url,method=method): self.assertEqual(self.call(self.other,method,url,json=body).status_code,404)
        self.assertEqual(self.call(self.other,'get','/api/v2/classes').json['classes'],[])
        self.assertEqual(self.call(self.other,'get',a['result']['pdf_url']).status_code,404)
        self.assertEqual(self.call(self.other,'post','/api/v2/exports/'+a['edition_id']).status_code,404)

    def test_foreign_edition_and_student_from_another_class_are_rejected(self):
        c,m,a,payload = self.assignment()
        other = self.classroom('9Б',['Другой ученик'],self.other)
        r = self.call(self.other,'post',f"/api/v2/classes/{other['id']}/assignments",json=dict(payload,revision=other['revision'],request_key=uuid.uuid4().hex))
        self.assertEqual(r.status_code,404)
        second = self.classroom('8Б',['Другой'])
        r = self.call(self.client,'put',f"/api/v2/classes/{second['id']}/students/{c['students'][0]['id']}",json={'name':'Имя','archived':True,'revision':second['revision']})
        self.assertEqual(r.status_code,404)

    def test_bulk_add_is_atomic_and_rejects_personal_names(self):
        c = self.classroom(names=['Семён Ёлкин'])
        path = f"/api/v2/classes/{c['id']}/students"
        for names in (['Новый','СЕМЁН ЁЛКИН'],['Дважды','дважды'],['Добрый',''],['x'*121],[],['x']*101):
            self.assertIn(self.call(self.client,'post',path,json={'names':names,'revision':c['revision']}).status_code,[400,409])
        fresh=class_store.get_class('max:11',c['id'])
        self.assertEqual(fresh['students'],c['students'])
        self.assertNotIn('name',fresh['students'][0])
        self.assertRegex(fresh['students'][0]['code'],r'^У-[A-F0-9]{10}$')
        self.assertEqual(fresh['revision'],c['revision'])

    def test_class_and_roster_revisions_prevent_lost_updates(self):
        c=self.classroom(names=['А'])
        path=f"/api/v2/classes/{c['id']}"
        changed=self.call(self.client,'put',path,json={'name':'8А · 2026','archived':False,'revision':c['revision']})
        self.assertEqual(changed.status_code,200)
        for value in (c['revision'],True,None):
            self.assertEqual(self.call(self.client,'post',path+'/students',json={'names':['Б'],'revision':value}).status_code,409)
        self.assertEqual(class_store.get_class('max:11',c['id'])['student_count'],1)
        self.assertEqual(self.call(self.client,'post','/api/v2/classes',json={'name':'8а · 2026'}).status_code,409)

    def test_assignment_keeps_exact_roster_and_edition_after_edits_and_archives(self):
        c,m,a,_=self.assignment()
        c=class_store.get_class('max:11',c['id'])
        s=c['students'][0]
        c=class_store.update_student('max:11',c['id'],s['id'],{'revision':c['revision'],'archived':True})
        c=class_store.add_students('max:11',c['id'],{'revision':c['revision'],'count':1})
        class_store.update_class('max:11',c['id'],{'revision':c['revision'],'name':'Новое название','archived':True})
        changed=dict(m['worksheet'],title='Другой лист')
        workspace_store.put_material('max:11',changed,'manual',m['id'],revision=1)
        workspace_store.organize_material('max:11',m['id'],'Архив',True)
        fresh=self.call(self.client,'get','/api/v2/assignments/'+a['id']).json['assignment']
        self.assertEqual(fresh['students'],a['students'])
        self.assertEqual(fresh['worksheet'],m['worksheet'])
        self.assertEqual(fresh['class_name'],'8А')
        self.assertEqual(fresh['code'],a['code'])
        self.assertEqual(fresh['due_date'],'2026-11-06')

    def test_assigned_material_cannot_be_deleted_even_when_assignment_closed(self):
        c,m,a,_=self.assignment()
        class_store.update_assignment('max:11',a['id'],{'status':'closed','revision':1})
        r=self.call(self.client,'delete','/api/v2/materials/'+m['id'],json={'revision':1})
        self.assertEqual(r.status_code,409); self.assertEqual(r.json['code'],'material_assigned')
        self.assertEqual(class_store.get_assignment('max:11',a['id'])['code'],a['code'])
        self.assertTrue(Path(self.temp.name,'job_'+a['edition_id']+'.pdf').exists())
        with workspace_store.connection() as conn:
            with self.assertRaises(sqlite3.IntegrityError): conn.execute('DELETE FROM artifacts WHERE id=?',(a['edition_id'],))

    def test_retry_after_roster_changed_returns_same_assignment_and_changed_payload_conflicts(self):
        c,m,a,payload=self.assignment()
        fresh=class_store.get_class('max:11',c['id'])
        class_store.add_students('max:11',c['id'],{'revision':fresh['revision'],'count':1})
        path=f"/api/v2/classes/{c['id']}/assignments"
        r=self.call(self.client,'post',path,json=payload)
        self.assertEqual(r.status_code,200); self.assertEqual(r.json['assignment']['id'],a['id'])
        self.assertEqual(r.json['assignment']['student_count'],2)
        r=self.call(self.client,'post',path,json=dict(payload,title='Другая работа'))
        self.assertEqual(r.status_code,409)
        self.assertEqual(len(class_store.get_class('max:11',c['id'])['assignments']),1)

    def test_concurrent_assignment_retries_create_one_record(self):
        c=self.classroom(names=['А'])
        m,edition=self.compiled()
        payload={'revision':c['revision'],'edition_id':edition,'title':'Один лист','request_key':uuid.uuid4().hex}
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _: class_store.assign('max:11',c['id'],payload),range(3)))
        self.assertEqual(len({a['id'] for a,created in results}),1)
        self.assertEqual(sum(created for a,created in results),1)

    def test_empty_archived_and_stale_rosters_cannot_receive_assignments(self):
        c=self.classroom()
        m,edition=self.compiled()
        path=f"/api/v2/classes/{c['id']}/assignments"
        payload={'revision':c['revision'],'edition_id':edition,'title':'Лист','request_key':uuid.uuid4().hex}
        self.assertEqual(self.call(self.client,'post',path,json=payload).json['code'],'empty_class')
        c=class_store.add_students('max:11',c['id'],{'revision':c['revision'],'count':1})
        self.assertEqual(self.call(self.client,'post',path,json=payload).json['code'],'revision_conflict')
        c=class_store.update_class('max:11',c['id'],{'revision':c['revision'],'name':c['name'],'archived':True})
        self.assertEqual(self.call(self.client,'post',path,json=dict(payload,revision=c['revision'])).json['code'],'class_archived')
        self.assertEqual(self.call(self.client,'post',f"/api/v2/classes/{c['id']}/students",json={'revision':c['revision'],'names':['Б']}).status_code,409)

    def test_archived_student_excluded_from_new_assignment_and_can_be_restored(self):
        c=self.classroom(names=['А','Б'])
        s=c['students'][0]
        other_code=c['students'][1]['code']
        c=class_store.update_student('max:11',c['id'],s['id'],{'revision':c['revision'],'archived':True})
        c,m,a,_=self.assignment(c)
        self.assertEqual([s['code'] for s in a['students']],[other_code])
        c=class_store.get_class('max:11',c['id'])
        c=class_store.update_student('max:11',c['id'],s['id'],{'revision':c['revision'],'archived':False})
        self.assertEqual(c['student_count'],2)
        self.assertEqual(class_store.get_assignment('max:11',a['id'])['student_count'],1)

    def test_status_uses_revision_and_archived_class_cannot_reopen_work(self):
        c,m,a,_=self.assignment()
        path='/api/v2/assignments/'+a['id']
        self.assertEqual(self.call(self.client,'put',path,json={'revision':1,'status':'closed'}).status_code,200)
        self.assertEqual(self.call(self.client,'put',path,json={'revision':1,'status':'active'}).status_code,409)
        c=class_store.get_class('max:11',c['id'])
        class_store.update_class('max:11',c['id'],{'revision':c['revision'],'name':c['name'],'archived':True})
        self.assertEqual(self.call(self.client,'put',path,json={'revision':2,'status':'active'}).status_code,409)

    def test_invalid_assignment_metadata_does_not_create_partial_work(self):
        c=self.classroom(names=['А'])
        m,edition=self.compiled()
        payload={'revision':c['revision'],'edition_id':edition,'title':'Лист','request_key':uuid.uuid4().hex}
        for patch in ({'due_date':'2026-02-30'},{'due_date':'20261106'},{'due_date':[]},{'title':''},{'title':'x'*161},
                      {'instructions':'x'*2001},{'instructions':{}},{'edition_id':{}},{'request_key':'short'}):
            r=self.call(self.client,'post',f"/api/v2/classes/{c['id']}/assignments",json=dict(payload,**patch))
            self.assertEqual(r.status_code,400,r.json)
        self.assertEqual(class_store.get_class('max:11',c['id'])['assignments'],[])

    def test_backup_restore_and_repeated_migration_preserve_roster_assignment_and_files(self):
        c,m,a,_=self.assignment()
        db.init_db(); db.init_db()
        self.login(self.client,11)
        self.assertEqual(self.call(self.client,'get','/api/v2/assignments/'+a['id']).json['assignment']['students'],a['students'])
        archive=Path(self.temp.name,'classes.zip'); backup.create_backup(archive)
        target=Path(self.temp.name,'restored'); backup.restore_backup(archive,target)
        with closing(sqlite3.connect(target/'worksheets.db')) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM classrooms').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM assignment_students').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT edition_id FROM assignments').fetchone()[0],a['edition_id'])
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertTrue((target/'generated'/('job_'+a['edition_id']+'.pdf')).is_file())
