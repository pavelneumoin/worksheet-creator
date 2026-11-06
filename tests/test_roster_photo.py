from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch, Mock
import uuid
import zipfile

from PIL import Image
import test_classes as classes
from utils import backup, db, job_store, roster_ai, roster_store, class_store, workspace_store
from utils.gigachat_client import AIServiceError


class RosterTests(unittest.TestCase):
    setUp = classes.ClassTests.setUp
    call = classes.ClassTests.call
    signed = classes.ClassTests.signed
    login = classes.ClassTests.login
    classroom = classes.ClassTests.classroom

    def ready(self):
        c = self.classroom()
        path = Path(self.temp.name)/'roster.png'; Image.new('RGB',(100,100),'white').save(path)
        job,_ = job_store.submit('max:11','roster_recognize',uuid.uuid4().hex,{'class_id':c['id']},[path],require_worker=False)
        claim = job_store.claim_next('ai')
        output = {'rows':[{'name':'Учебный Альфа','uncertain':False},{'name':'','uncertain':True}], 'too_many':False}
        self.assertTrue(job_store.complete(claim,output))
        job_store.remove_inputs(job['id'])
        return c,job['id']

    def test_result_is_private_no_cache_not_in_database_or_backup_and_can_be_discarded(self):
        c,job = self.ready();url=f'/api/v2/jobs/{job}/roster'
        response = self.call(self.client,'get',url)
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.json['rows'][0]['name'],'Учебный Альфа')
        self.assertEqual(self.call(self.other,'get',url).status_code,404)
        self.assertEqual(self.call(self.anon,'get',url).status_code,401)
        self.assertEqual(self.call(self.other,'delete',url).status_code,404)
        self.assertEqual(self.call(self.client,'delete',url,headers={'X-CSRF-Token':'wrong'}).status_code,403)
        with workspace_store.connection() as conn:
            self.assertNotIn('Учебный Альфа','\n'.join(conn.iterdump()))
        archive=Path(self.temp.name)/'copy.zip';backup.create_backup(archive)
        with zipfile.ZipFile(archive) as z:
            self.assertFalse(any('roster_results' in name for name in z.namelist()))
            z.extract('worksheets.db',Path(self.temp.name)/'restore')
        with closing(sqlite3.connect(Path(self.temp.name)/'restore/worksheets.db')) as conn:
            self.assertNotIn('Учебный Альфа','\n'.join(conn.iterdump()))
        self.assertEqual(self.call(self.client,'delete',url).status_code,200)
        self.assertFalse(roster_store.result_path(job).exists())
        self.assertEqual(self.call(self.client,'get',url).status_code,410)
        self.assertFalse(job_store.job_directory(job).exists())

    def test_expiry_removes_results_and_abandoned_uploads(self):
        c,job=self.ready()
        future=time.time()+roster_store.TTL+2
        with patch('utils.roster_store.time.time',return_value=future):
            job_store.maintain()
        self.assertFalse(roster_store.result_path(job).exists())
        path=Path(self.temp.name)/'image.png';Image.new('RGB',(50,50)).save(path)
        queued,_=job_store.submit('max:11','roster_recognize',uuid.uuid4().hex,{'class_id':c['id']},[path],require_worker=False)
        with patch('utils.roster_store.time.time',return_value=future):job_store.maintain()
        self.assertEqual(job_store.get_job('max:11',queued['id'])['status'],'failed')
        self.assertFalse(job_store.job_directory(queued['id']).exists())

    def test_concurrent_retry_keeps_exact_code_order_and_does_not_duplicate(self):
        c=self.classroom();payload={'count':3,'revision':c['revision'],'request_key':uuid.uuid4().hex}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:roster_store.import_codes('max:11',c['id'],payload),range(2)))
        self.assertEqual(results[0]['students'],results[1]['students'])
        self.assertEqual(class_store.get_class('max:11',c['id'])['student_count'],3)
        payload['revision']+=1
        again=roster_store.import_codes('max:11',c['id'],payload)
        self.assertTrue(again['reused']);self.assertEqual(again['students'],results[0]['students'])
        with self.assertRaises(AIServiceError):roster_store.import_codes('max:11',c['id'],{**payload,'count':4})
        self.assertEqual(class_store.get_class('max:11',c['id'])['student_count'],3)

    def test_import_requires_owner_csrf_revision_and_never_accepts_names(self):
        c=self.classroom();url=f"/api/v2/classes/{c['id']}/roster-imports"
        payload={'count':2,'revision':c['revision'],'request_key':uuid.uuid4().hex}
        self.assertEqual(self.call(self.other,'post',url,json=payload).status_code,404)
        self.assertEqual(self.call(self.anon,'post',url,json=payload).status_code,401)
        self.assertEqual(self.call(self.client,'post',url,json=payload,headers={'X-CSRF-Token':'wrong'}).status_code,403)
        self.assertEqual(self.call(self.client,'post',url,json={**payload,'names':['Иван']}).status_code,400)
        self.assertEqual(self.call(self.client,'post',url,json={**payload,'revision':99}).status_code,409)
        self.assertEqual(self.call(self.client,'post',url,json={**payload,'count':True}).status_code,400)
        result=self.call(self.client,'post',url,json=payload)
        self.assertEqual(result.status_code,201);self.assertEqual(len(result.json['students']),2)
        self.assertEqual(self.call(self.client,'post',url,json=payload).status_code,200)

    def test_upload_requires_disclosed_processing_and_image_limits(self):
        c=self.classroom();job_store.heartbeat('fixture','ai');url='/api/v2/jobs/roster_recognize'
        def send(client=None,consent='true',content=b'\x89PNG\r\n\x1a\nfixture',name='photo.png'):
            return self.call(client or self.client,'post',url,headers={'Idempotency-Key':uuid.uuid4().hex},
                             data={'class_id':c['id'],'consent':consent,'files':(io.BytesIO(content),name)})
        with patch('job_api.get_ai_status',return_value={'ai_ready':True}):
            self.assertEqual(send(self.other).status_code,404)
            self.assertEqual(send(consent='false').status_code,400)
            self.assertEqual(send(content=b'%PDF-fixture',name='list.pdf').status_code,415)
            self.assertEqual(send(content=b'\xff\xd8\xff'+b'0'*(15*1024*1024),name='big.jpg').status_code,413)
            result=send();self.assertEqual(result.status_code,202,result.json)
        self.assertEqual(result.json['job']['kind'],'roster_recognize')
        self.assertEqual(class_store.get_class('max:11',c['id'])['student_count'],0)
        job_store.cancel('max:11',result.json['job']['id'])
        self.assertFalse(job_store.job_directory(result.json['job']['id']).exists())

    def test_uncertain_empty_and_duplicate_rows_are_not_silently_dropped(self):
        source={'rows':[{'name':'Петров Иван','uncertain':False},{'name':'','uncertain':False},{'name':'Петров Иван','uncertain':True}],'too_many':False,'instructions':'untrusted'}
        result=roster_ai.validate(source)
        self.assertEqual(len(result['rows']),3);self.assertTrue(result['rows'][1]['uncertain']);self.assertNotIn('instructions',result)
        for invalid in ({'rows':[], 'too_many':True},{'rows':[{'name':'x\nY','uncertain':False}],'too_many':False},{'rows':[{'name':'x','uncertain':'false'}],'too_many':False}):
            with self.assertRaises(AIServiceError):roster_ai.validate(invalid)

    def test_provider_file_is_deleted_on_invalid_model_response(self):
        path=Path(self.temp.name)/'image.jpg';path.write_bytes(b'fixture')
        client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
        client.upload_file.return_value.id_='fixture-file'
        client.chat.return_value.choices=[Mock(finish_reason='stop',message=Mock(content='invalid json'))]
        with patch('utils.roster_ai._create_client',return_value=client):
            with self.assertRaises(AIServiceError):roster_ai.recognize([path])
        client.delete_file.assert_called_once_with('fixture-file')
        with workspace_store.connection() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM provider_uploads').fetchone()[0],0)

    def test_cancelled_or_stale_worker_cannot_publish_names(self):
        c=self.classroom();job,_=job_store.submit('max:11','roster_recognize',uuid.uuid4().hex,{'class_id':c['id']},require_worker=False)
        claim=job_store.claim_next('ai');job_store.fail(job['id'],claim['claim'],'Interrupted','fixture')
        self.assertFalse(job_store.complete(claim,{'rows':[{'name':'Нельзя сохранить','uncertain':False}],'too_many':False}))
        self.assertFalse(roster_store.result_path(job['id']).exists())

    def test_empty_second_page_never_looks_like_a_complete_list(self):
        path=Path(self.temp.name)/'image.jpg';path.write_bytes(b'fixture')
        client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
        client.upload_file.side_effect=[Mock(id_='first-file'),Mock(id_='second-file')]
        responses=[{'rows':[{'name':'Учебный Альфа','uncertain':False}],'too_many':False},{'rows':[],'too_many':False}]
        client.chat.side_effect=[Mock(choices=[Mock(finish_reason='stop',message=Mock(content=json.dumps(value)))]) for value in responses]
        with patch('utils.roster_ai._create_client',return_value=client):
            with self.assertRaises(AIServiceError) as error:roster_ai.recognize([path,path])
        self.assertEqual(error.exception.code,'roster_empty');self.assertEqual(client.delete_file.call_count,2)


if __name__=='__main__':unittest.main()
