import json
import time
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

import test_personal as personal
from utils import demo_space, workspace_store, analytics, review_store, batch_review, library_store, school_store, backup
from utils.gigachat_client import AIServiceError
from pypdf import PdfReader


class DemoTests(unittest.TestCase):
    setUp=personal.PersonalTests.setUp
    call=personal.PersonalTests.call
    signed=personal.PersonalTests.signed
    login=personal.PersonalTests.login
    create=personal.PersonalTests.create

    def enter(self,client=None):
        client=client or self.client
        r=self.call(client,'post','/api/v2/demo-space/enter')
        self.assertEqual(r.status_code,200,r.json)
        return self.call(client,'get','/api/v2/demo-space').json['demo']

    def test_complete_scenario_is_private_idempotent_and_returns_to_real_data(self):
        real=self.create()
        school_store.create('max:11',{'name':'Настоящая школа'})
        d=self.enter();again=self.enter()
        self.assertEqual(d,again)
        self.assertTrue(self.call(self.client,'get','/api/v2/auth/me').json['demo'])
        materials=self.call(self.client,'get','/api/v2/materials').json['materials']
        self.assertEqual(len(materials),4)
        self.assertNotIn(real['id'],[m['id'] for m in materials])
        self.assertEqual(self.call(self.client,'get','/api/v2/materials/'+real['id']).status_code,404)
        self.assertEqual(self.call(self.other,'get','/api/v2/classes/'+d['classes'][0]).status_code,404)
        with self.call(self.client,'get',d['sample_pdf']['pdf_url']) as response:self.assertEqual(response.status_code,200)
        ticket=self.call(self.client,'post','/api/v2/exports/'+d['sample_pdf']['artifact_id']).json['pdf_url']
        with self.call(self.anon,'get',ticket) as response:self.assertEqual(response.status_code,200)
        report=self.call(self.client,'get','/api/v2/analytics?scope=school').json['report']
        self.assertEqual(report['totals']['classes'],3)
        self.assertEqual(report['totals']['confirmed'],24)
        self.assertEqual(report['totals']['needs_review'],4)
        self.assertGreater(report['totals']['not_submitted'],0)
        self.assertEqual(self.call(self.client,'post','/api/v2/demo-space/exit').status_code,200)
        self.assertFalse(self.call(self.client,'get','/api/v2/auth/me').json['demo'])
        self.assertEqual(self.call(self.client,'get','/api/v2/materials').json['materials'],[real])
        self.assertEqual(school_store.current('max:11')['name'],'Настоящая школа')
        self.assertEqual(self.call(self.client,'get',d['sample_pdf']['pdf_url']).status_code,404)
        self.assertEqual(self.call(self.anon,'get',ticket).status_code,404)
        self.assertEqual(self.enter(),d)

    def test_demo_publications_and_school_invitations_cannot_cross_realms(self):
        first=self.enter();second=self.enter(self.other)
        with workspace_store.connection() as conn:
            owners={r['real_owner']:r['demo_owner'] for r in conn.execute('SELECT * FROM demo_spaces')}
        a,b=owners['max:11'],owners['max:22']
        pub=library_store.list_publications(a)['publications'][0]
        self.assertEqual(library_store.list_publications('max:11')['total'],0)
        for other in (b,'max:11'):
            for action in (lambda:library_store.get_publication(other,pub['id']),
                           lambda:library_store.rate(other,pub['id'],1),
                           lambda:library_store.copy_to_materials(other,pub['id'])):
                with self.assertRaises(AIServiceError):action()
        invite=school_store.invite(a)['code']
        with self.assertRaises(AIServiceError):school_store.join('max:22',{'code':invite,'share_statistics':True})
        self.assertIsNone(school_store.current('max:22'))
        self.assertEqual(self.call(self.other,'get','/api/v2/reviews/'+first['review']).status_code,404)
        self.assertNotEqual(first['review'],second['review'])

    def test_seeded_review_and_batch_use_normal_confirmation_and_statistics(self):
        d=self.enter()
        with workspace_store.connection() as conn:owner=conn.execute('SELECT demo_owner FROM demo_spaces').fetchone()[0]
        before=analytics.overview(owner,{})['totals']['confirmed']
        r=review_store.get_review(owner,d['review'])
        self.assertEqual(r['status'],'needs_review');self.assertTrue(r['photos'])
        self.assertTrue(any(a['score'] is None for a in r['answers']))
        body={'revision':r['revision'],'action':'confirm','reviewed':True,'comment':'Учебная проверка',
              'answers':[dict(task_id=a['task_id'],text=a['text'],score=.5,comment='') for a in r['answers']]}
        review_store.update(owner,r['id'],body)
        self.assertEqual(analytics.overview(owner,{})['totals']['confirmed'],before+1)
        batch=batch_review.get(owner,d['batch'])
        result=batch_review.attach(owner,d['batch'],{'revision':batch['revision'],'pages':[0],
                                  'student_id':batch['pages'][0]['suggested_student_id']})
        self.assertTrue(result)
        self.assertEqual(analytics.overview(owner,{})['totals']['confirmed'],before+1)

    def test_auth_csrf_and_missing_assets_leave_no_half_workspace(self):
        self.assertEqual(self.call(self.anon,'post','/api/v2/demo-space/enter').status_code,401)
        self.assertEqual(self.call(self.client,'post','/api/v2/demo-space/enter',headers={'X-CSRF-Token':'bad'}).status_code,403)
        with patch.object(demo_space,'ASSETS',Path(self.temp.name)/'absent'):
            self.assertEqual(self.call(self.client,'post','/api/v2/demo-space/enter').status_code,503)
        with workspace_store.connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM demo_spaces').fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE kind='demo'").fetchone()[0],0)

    def test_max_refresh_and_backup_keep_data_without_restoring_demo_session(self):
        d=self.enter()
        self.login(self.client,11)
        self.assertTrue(self.call(self.client,'get','/api/v2/auth/me').json['demo'])
        self.assertEqual(self.call(self.client,'get','/api/v2/demo-space').json['demo'],d)
        archive=Path(self.temp.name)/'demo-backup.zip'
        backup.create_backup(archive)
        restored=Path(self.temp.name)/'restored'
        backup.restore_backup(archive,restored)
        import sqlite3
        with closing(sqlite3.connect(restored/'worksheets.db')) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM demo_spaces').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM demo_sessions').fetchone()[0],0)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_expired_prepared_scan_is_restored_on_demo_reentry(self):
        d=self.enter()
        with workspace_store.connection() as conn:
            conn.execute('UPDATE reviews SET photo_expires=?,photo_count=0 WHERE id=?',(time.time()-1,d['review']))
            conn.execute("UPDATE review_batches SET expires_at=?,photo_count=0,pages='[]' WHERE id=?",(time.time()-1,d['batch']))
        review_store.photo_path(d['review'],0).unlink()
        batch_review.photo(d['batch'],0).unlink()
        self.enter()
        response=self.call(self.client,'get','/api/v2/reviews/'+d['review']).json
        self.assertTrue(response['review']['photos'])
        response=self.call(self.client,'get','/api/v2/batches/'+d['batch']).json['batch']
        self.assertEqual(len(response['pages']),1)
        self.assertFalse(response['expired'])

    def test_shipped_pdf_codes_and_page_counts_match_the_current_catalog(self):
        from utils.demo_catalog import sheets
        from utils.worksheet import edition_code
        for key,sheet in sheets().items():
            for suffix,count in [('',1),('_keys',1),('_teacher',2)]:
                with (demo_space.ASSETS/(key+suffix+'.pdf')).open('rb') as stream:
                    reader=PdfReader(stream)
                    self.assertEqual(len(reader.pages),count)
                    self.assertIn(edition_code(sheet),reader.pages[0].extract_text())
                    fonts={str(f.get_object().get('/BaseFont')) for page in reader.pages for f in page['/Resources']['/Font'].values()}
                    self.assertTrue(any('CMUSerif' in f for f in fonts))
