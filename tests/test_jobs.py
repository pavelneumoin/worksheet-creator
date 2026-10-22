"""Queue lifecycle, ownership, race prevention and failure recovery, without paid AI."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import uuid

import test_personal as personal
from utils import job_store, job_runner, workspace_store
from utils.worksheet import demo_worksheet


class JobTests(unittest.TestCase):
    setUp = personal.PersonalTests.setUp
    call = personal.PersonalTests.call
    signed = personal.PersonalTests.signed
    login = personal.PersonalTests.login
    create = personal.PersonalTests.create

    def enqueue(self, client=None, key=None, material=None):
        material = material or self.create()
        job_store.heartbeat('test-worker', 'compile')
        return self.call(client or self.client, 'post', '/api/v2/jobs/compile',
                         headers={'Idempotency-Key': key or uuid.uuid4().hex},
                         json={'worksheet': material['worksheet'], 'material_id': material['id'],
                               'revision': material['revision'], 'reviewed': True})

    def test_idempotent_submission_and_other_profile_cannot_read_cancel(self):
        material, key = self.create(), uuid.uuid4().hex
        first = self.enqueue(key=key, material=material)
        second = self.enqueue(key=key, material=material)
        self.assertEqual(first.status_code, 202, first.json)
        self.assertEqual(first.json['job']['id'], second.json['job']['id'])
        self.assertTrue(second.json['reused'])
        path = '/api/v2/jobs/' + first.json['job']['id']
        for method, suffix in [('get', ''), ('post', '/cancel'), ('post', '/acknowledge')]:
            self.assertEqual(self.call(self.other, method, path + suffix).status_code, 404)
        self.assertEqual(self.call(self.other, 'get', '/api/v2/jobs').json['jobs'], [])
        self.assertEqual(self.call(self.anon, 'get', path).status_code, 401)

    def test_reused_key_rejects_changed_content_and_one_active_per_owner(self):
        first, second, key = self.create(), self.create(), uuid.uuid4().hex
        self.assertEqual(self.enqueue(key=key, material=first).status_code, 202)
        conflict = self.enqueue(key=key, material=second)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json['code'], 'request_key_conflict')
        self.assertEqual(self.enqueue(material=second).status_code, 429)

    def test_only_one_worker_can_claim_lane(self):
        job = self.enqueue().json['job']
        other = job_store.submit('max:22', 'recognize', uuid.uuid4().hex,
                                {'subject':'math', 'text':'2+2'}, require_worker=False)[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: job_store.claim_next('compile'), range(4)))
        self.assertEqual(sum(row is not None for row in claims), 1)
        self.assertEqual(next(row['id'] for row in claims if row), job['id'])
        self.assertEqual(job_store.claim_next('ai')['id'], other['id'])

    def test_queue_survives_relogin_and_queued_cancel_cleans_files(self):
        job = self.enqueue().json['job']
        directory = job_store.job_directory(job['id'])
        self.assertTrue(directory.is_dir())
        self.login(self.client, 11)
        self.assertEqual(self.call(self.client, 'get', '/api/v2/jobs').json['jobs'][0]['id'], job['id'])
        cancelled = self.call(self.client, 'post', '/api/v2/jobs/' + job['id'] + '/cancel')
        self.assertEqual(cancelled.json['job']['status'], 'cancelled')
        self.assertFalse(directory.exists())
        self.assertIsNone(job_store.claim_next('compile'))

    def test_lost_worker_fails_without_retry_and_cannot_complete(self):
        job_id = self.enqueue().json['job']['id']
        claimed = job_store.claim_next('compile')
        self.assertEqual(self.call(self.client, 'post', '/api/v2/jobs/' + job_id + '/cancel').status_code, 409)
        with workspace_store.connection() as conn:
            conn.execute('UPDATE jobs SET heartbeat=? WHERE id=?', (time.time()-60, job_id))
        job_store.maintain()
        result = job_store.get_job('max:11', job_id)
        self.assertEqual((result['status'], result['error_code']), ('failed', 'worker_interrupted'))
        self.assertIsNone(job_store.claim_next('compile'))
        self.assertFalse(job_store.complete(claimed, {'ok':True}))
        self.assertFalse(job_store.job_directory(job_id).exists())

    def test_ai_completion_saves_material_atomically_and_ack_only_hides_job(self):
        job, _ = job_store.submit('max:11', 'recognize', uuid.uuid4().hex,
                                 {'subject':'math', 'text':'2+2'}, require_worker=False)
        claimed = job_store.claim_next('ai')
        self.assertTrue(job_store.complete(claimed, {'worksheet':demo_worksheet('math')}))
        self.assertFalse(job_store.complete(claimed, {'worksheet':demo_worksheet('math')}))
        material_id = job_store.get_job('max:11', job['id'])['result']['material_id']
        self.assertEqual(self.call(self.client,'get','/api/v2/materials/'+material_id).status_code, 200)
        job_store.acknowledge('max:11', job['id'])
        self.assertEqual(job_store.list_jobs('max:11'), [])
        self.assertEqual(self.call(self.client,'get','/api/v2/materials/'+material_id).status_code, 200)

    def test_compile_never_overwrites_edits_made_while_running(self):
        material = self.create()
        self.enqueue(material=material)
        claimed = job_store.claim_next('compile')
        changed = dict(material['worksheet'], title='Новая версия учителя')
        response = self.call(self.client,'put','/api/v2/materials/'+material['id'],
                             json={'worksheet':changed,'revision':material['revision']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(job_store.complete(claimed, {'ok':True}))
        job = job_store.get_job('max:11', claimed['id'])
        self.assertFalse(job['result']['attached'])
        self.assertIsNone(job['result']['material_id'])
        fresh = self.call(self.client,'get','/api/v2/materials/'+material['id']).json['material']
        self.assertEqual(fresh['worksheet']['title'], 'Новая версия учителя')
        self.assertIsNone(fresh['result'])

    def test_marp_download_requires_owner_and_native_ticket_expires(self):
        self.enqueue()
        claimed = job_store.claim_next('compile')
        job_store.complete(claimed, {'ok':True})
        result = job_store.get_job('max:11', claimed['id'])['result']
        name = result['marp_url'].rsplit('/',1)[-1]
        Path(self.temp.name, name).write_bytes(b'PK-test')
        response = self.call(self.client,'get',result['marp_url'])
        self.assertEqual(response.status_code, 200); response.close()
        self.assertEqual(self.call(self.other,'get',result['marp_url']).status_code,404)
        links = self.call(self.client,'post','/api/v2/exports/'+result['artifact_id']).json
        response = self.call(self.anon,'get',links['marp_url'])
        self.assertEqual(response.status_code,200); response.close()
        with workspace_store.connection() as conn:
            conn.execute('UPDATE download_tickets SET expires_at=0')
        self.assertEqual(self.call(self.anon,'get',links['marp_url']).status_code,404)

    def test_no_worker_fails_fast_and_legacy_cannot_bypass_queue(self):
        material = self.create()
        result = self.call(self.client,'post','/api/v2/jobs/compile',headers={'Idempotency-Key':uuid.uuid4().hex},
                           json={'worksheet':material['worksheet'],'material_id':material['id'],'revision':1,'reviewed':True})
        self.assertEqual(result.status_code,503)
        for path in ('/api/v2/compile','/api/v2/recognize','/api/v2/variant','/api/process','/api/compile','/api/generate_similar'):
            self.assertEqual(self.call(self.client,'post',path).status_code,410,path)

    def test_worker_timeout_stops_child_without_publishing_result(self):
        job_id = self.enqueue().json['job']['id']
        # The real child is stopped before it can finish; never call a provider.
        self.assertTrue(job_runner.run_one('compile','timeout-worker',timeout_override=-1))
        result = job_store.get_job('max:11',job_id)
        self.assertEqual(result['error_code'],'job_timeout')
        self.assertFalse(job_store.job_directory(job_id).exists())

    def test_private_photos_staged_only_for_valid_authenticated_request(self):
        job_store.heartbeat('test-ai','ai')
        with patch('job_api.get_ai_status',return_value={'ai_ready':True}):
            response = self.call(self.client,'post','/api/v2/jobs/recognize',headers={'Idempotency-Key':uuid.uuid4().hex},
                                 data={'files':(io.BytesIO(b'not a photo'),'x.png')})
            self.assertEqual(response.status_code,415)
            response = self.call(self.client,'post','/api/v2/jobs/recognize',headers={'Idempotency-Key':uuid.uuid4().hex},
                                 data={'files':(io.BytesIO(b'\x89PNG\r\n\x1a\nfixture'),'x.png')})
        self.assertEqual(response.status_code,202,response.json)
        job_id = response.json['job']['id']
        self.assertEqual((job_store.job_directory(job_id)/'0.png').read_bytes(),b'\x89PNG\r\n\x1a\nfixture')
        job_store.cancel('max:11',job_id)
        self.assertFalse(job_store.job_directory(job_id).exists())


if __name__ == '__main__': unittest.main()
