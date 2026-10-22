"""PDF decoding, batch recovery, coded rosters and the private lesson calendar."""
from copy import deepcopy
import io
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import uuid

from PIL import Image
from pypdf import PdfWriter
import test_personal as personal
import test_classes as classes
import test_cabinet_storage as cabinet
from utils import ai_batch, class_store, job_store, job_runner, source_pages, student_privacy, workspace_store
from utils.gigachat_client import AIServiceError
from utils.worksheet import demo_worksheet


class VoiceRequirementsTests(unittest.TestCase):
    setUp = personal.PersonalTests.setUp
    call = personal.PersonalTests.call
    signed = personal.PersonalTests.signed
    login = personal.PersonalTests.login
    create = personal.PersonalTests.create
    classroom = classes.ClassTests.classroom
    compiled = cabinet.CabinetTests.compiled
    assignment = classes.ClassTests.assignment

    def pdf(self, pages=2, password=None, width=595):
        path = Path(self.temp.name, uuid.uuid4().hex + '.pdf')
        writer = PdfWriter()
        for _ in range(pages): writer.add_blank_page(width=width, height=842)
        if password: writer.encrypt(password)
        writer.write(path)
        return path

    def test_pdf_pages_render_in_order_with_bounded_dimensions(self):
        paths = source_pages.prepare([self.pdf()], Path(self.temp.name, 'pages'))
        self.assertEqual(len(paths), 2)
        for path in paths:
            with Image.open(path) as image:
                self.assertEqual(image.format, 'JPEG')
                self.assertLessEqual(max(image.size), 2200)
                self.assertFalse(image.getexif())

    def test_encrypted_corrupt_oversized_pdf_are_rejected_before_ai(self):
        bad = Path(self.temp.name, 'bad.pdf'); bad.write_bytes(b'%PDF-broken')
        for path, code in [(self.pdf(11), 'page_limit'), (self.pdf(password='secret'), 'invalid_pdf'),
                           (bad, 'invalid_pdf'), (self.pdf(width=50000), 'invalid_pdf')]:
            with self.subTest(code=code), self.assertRaises(AIServiceError) as raised:
                source_pages.prepare([path], Path(self.temp.name, uuid.uuid4().hex))
            self.assertEqual(raised.exception.code, code)

    def test_camera_orientation_and_metadata_are_normalized(self):
        path = Path(self.temp.name, 'photo.jpg')
        exif = Image.Exif(); exif[274] = 6; exif[315] = 'private camera owner'
        with Image.new('RGB', (200, 100), 'white') as image: image.save(path, exif=exif)
        result = source_pages.prepare([path], Path(self.temp.name, 'pages'))
        with Image.open(result[0]) as image:
            self.assertEqual(image.size, (100, 200))
            self.assertFalse(image.getexif())

    def recognize(self, data):
        job_store.heartbeat('ai-fixture', 'ai')
        with patch('job_api.get_ai_status', return_value={'ai_ready': True}):
            return self.call(self.client, 'post', '/api/v2/jobs/recognize', data=data,
                             headers={'Idempotency-Key': uuid.uuid4().hex})

    def test_recognize_accepts_pdf_and_validates_upfront_settings(self):
        pdf = self.pdf(1)
        response = self.recognize({'files': (io.BytesIO(pdf.read_bytes()), 'source.pdf'),
                                  'variant_count':'4', 'instructions':'Только № 2',
                                  'settings':json.dumps({'template':'list','columns':2,'field':'none','tasks_per_page':6})})
        self.assertEqual(response.status_code, 202, response.json)
        claimed = job_store.claim_next('ai'); payload = json.loads(claimed['payload'])
        self.assertEqual(payload['settings']['columns'], 2)
        self.assertEqual(payload['variant_count'], 4)
        self.assertEqual(payload['instructions'], 'Только № 2')
        self.assertEqual(payload['images'], ['0.pdf'])

    def test_invalid_counts_settings_and_mixed_pdf_do_not_enqueue(self):
        for patch_value in ({'variant_count':'5'}, {'variant_count':'true'}, {'variant_count':'0'},
                            {'settings':'[]'}, {'settings':'{"columns":3}'}, {'settings':'broken'},
                            {'instructions':'x'*2001}, {'files':[(io.BytesIO(b'%PDF-x'),'a.pdf'),(io.BytesIO(b'%PDF-y'),'b.pdf')]}):
            response = self.recognize(dict({'text':'2+2'}, **patch_value))
            self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(job_store.list_jobs('max:11'), [])

    def fixture_sheets(self, count):
        result = []
        for i in range(count):
            sheet = demo_worksheet('math')
            for task in sheet['tasks']: task['question'] = f'{i+1}. ' + task['question']
            result.append(sheet)
        return result

    def test_batch_saves_all_variants_atomically_and_preserves_preferences(self):
        settings = dict(demo_worksheet('math')['settings'], template='guided', columns=2)
        payload = {'subject':'math','text':'Источник','instructions':'Без № 3','settings':settings,'variant_count':4}
        job,_ = job_store.submit('max:11','recognize',uuid.uuid4().hex,payload,require_worker=False)
        claimed = job_store.claim_next('ai')
        with patch('utils.structured_ai.generate', side_effect=self.fixture_sheets(4)) as mocked:
            output = ai_batch.generate('recognize',payload,[],job_store.job_directory(job['id']))
        self.assertEqual(mocked.call_args_list[0].kwargs['instructions'], 'Без № 3')
        # Real variants inherit settings in structured_ai; emulate that contract in the fixture.
        self.assertEqual(output['worksheets'][0]['settings']['template'], 'guided')
        self.assertEqual([w['settings']['variant'] for w in output['worksheets']], ['1','2','3','4'])
        self.assertTrue(job_store.complete(claimed,output))
        self.assertFalse(job_store.complete(claimed,output))
        result=job_store.get_job('max:11',job['id'])['result']
        self.assertEqual(len({m['material_id'] for m in result['materials']}),4)
        for m in result['materials']:
            self.assertEqual(self.call(self.other,'get','/api/v2/materials/'+m['material_id']).status_code,404)

    def test_failed_second_variant_keeps_first_with_explicit_warning(self):
        payload={'subject':'math','text':'2+2','variant_count':3}
        directory=Path(self.temp.name,'batch'); directory.mkdir()
        with patch('utils.structured_ai.generate',side_effect=[demo_worksheet('math'),AIServiceError('Ошибка ИИ','ai_unavailable',503)]):
            output=ai_batch.generate('recognize',payload,[],directory)
        self.assertEqual(len(output['worksheets']),1)
        self.assertIn('1 из 3',output['warning'])
        self.assertEqual(json.loads((directory/'result.json').read_text(encoding='utf-8')),output)

    def test_repeated_questions_are_not_saved_as_a_new_variant(self):
        payload={'subject':'math','text':'2+2','variant_count':2}
        directory=Path(self.temp.name,'batch'); directory.mkdir()
        with patch('utils.structured_ai.generate',side_effect=[demo_worksheet('math'),demo_worksheet('math')]):
            output=ai_batch.generate('recognize',payload,[],directory)
        self.assertEqual(len(output['worksheets']),1)
        self.assertIn('повторил',output['warning'])

    def test_worker_restart_recovers_checkpoint_without_provider_replay(self):
        job,_=job_store.submit('max:11','recognize',uuid.uuid4().hex,{'subject':'math','text':'2+2','variant_count':3},require_worker=False)
        claimed=job_store.claim_next('ai')
        ai_batch.write_result(job_store.job_directory(job['id']), {'worksheets':[demo_worksheet('math')],'warning':'Сохранён 1 из 3 вариантов'})
        with workspace_store.connection() as conn:
            conn.execute('UPDATE jobs SET heartbeat=? WHERE id=?',(time.time()-60,job['id']))
        with patch('utils.structured_ai.generate') as model:
            job_store.maintain(); model.assert_not_called()
        saved=job_store.get_job('max:11',job['id'])
        self.assertEqual(saved['status'],'succeeded')
        self.assertEqual(len(saved['result']['materials']),1)
        self.assertFalse(job_store.complete(claimed,{'worksheets':self.fixture_sheets(3)}))
        self.assertFalse(job_store.job_directory(job['id']).exists())

    def test_invalid_batch_does_not_leave_partial_materials(self):
        job,_=job_store.submit('max:11','recognize',uuid.uuid4().hex,{'subject':'math','text':'x','variant_count':2},require_worker=False)
        claimed=job_store.claim_next('ai')
        with self.assertRaises(AIServiceError): job_store.complete(claimed,{'worksheets':[demo_worksheet('math'),{}]})
        with workspace_store.connection() as conn: self.assertEqual(conn.execute('SELECT COUNT(*) FROM materials').fetchone()[0],0)

    def test_coded_students_reject_names_and_count_limits_without_db_writes(self):
        c=self.classroom(names=['fixture'])
        for value in ({'count':0},{'count':101},{'count':True},{'count':'2'},{'count':1,'name':'Private Person'}):
            r=self.call(self.client,'post',f"/api/v2/classes/{c['id']}/students",json=dict(value,revision=c['revision']))
            self.assertEqual(r.status_code,400)
        r=self.call(self.client,'put',f"/api/v2/classes/{c['id']}/students/{c['students'][0]['id']}",json={'revision':c['revision'],'archived':False,'name':'Private Person'})
        self.assertEqual(r.status_code,400)
        with workspace_store.connection() as conn:
            self.assertEqual([s['name'] for s in conn.execute('SELECT name FROM students')],[c['students'][0]['code']])

    def test_legacy_privacy_migration_exports_before_changes_and_is_repeatable(self):
        c,m,a,_=self.assignment()
        with workspace_store.connection() as conn:
            conn.execute("UPDATE students SET name='Private Person'")
            conn.execute("UPDATE assignment_students SET name='Old Private Name'")
        target=Path(self.temp.name,'private.csv'); target.write_text('existing',encoding='utf-8')
        with self.assertRaises(FileExistsError): student_privacy.migrate(target)
        with workspace_store.connection() as conn: self.assertEqual(conn.execute('SELECT name FROM students LIMIT 1').fetchone()[0],'Private Person')
        second=Path(self.temp.name,'new.csv'); result=student_privacy.migrate(second)
        self.assertEqual(result['students'],2)
        self.assertIn('Private Person',second.read_text(encoding='utf-8-sig'))
        self.assertEqual(student_privacy.migrate(second)['students'],0)
        self.assertEqual(class_store.get_assignment('max:11',a['id'])['students'],a['students'])
        with workspace_store.connection() as conn:
            self.assertTrue(all(r[0].startswith('У-') for r in conn.execute('SELECT name FROM students UNION ALL SELECT name FROM assignment_students')))
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_calendar_is_owner_scoped_and_separates_lesson_from_deadline(self):
        c=self.classroom(names=['fixture']); m,edition=self.compiled()
        payload={'revision':c['revision'],'edition_id':edition,'title':'Lesson','scheduled_date':'2026-10-29','due_date':'2026-11-02','request_key':uuid.uuid4().hex}
        a,_=class_store.assign('max:11',c['id'],payload)
        self.assertEqual(class_store.schedule('max:11','2026-10')[0]['id'],a['id'])
        self.assertEqual(class_store.schedule('max:11','2026-11'),[])
        self.assertEqual(self.call(self.other,'get','/api/v2/schedule?month=2026-10').json['assignments'],[])
        self.assertEqual(self.call(self.anon,'get','/api/v2/schedule?month=2026-10').status_code,401)
        again,created=class_store.assign('max:11',c['id'],payload)
        self.assertFalse(created); self.assertEqual(again['id'],a['id'])
        with self.assertRaises(AIServiceError): class_store.assign('max:11',c['id'],dict(payload,scheduled_date='2026-10-30'))
        for month in ('2026-13','2026-1','bad','0000-01'):
            self.assertEqual(self.call(self.client,'get','/api/v2/schedule?month='+month).status_code,400)

    def test_invalid_lesson_date_or_earlier_deadline_is_rejected(self):
        c=self.classroom(names=['fixture']); m,edition=self.compiled()
        payload={'revision':c['revision'],'edition_id':edition,'title':'Lesson','request_key':uuid.uuid4().hex}
        for value in ({'scheduled_date':'2026-02-30'}, {'scheduled_date':True}, {'scheduled_date':'2026-10-29','due_date':'2026-10-28'}):
            with self.assertRaises(AIServiceError): class_store.assign('max:11',c['id'],dict(payload,**value))
