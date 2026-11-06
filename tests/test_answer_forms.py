"""Private answer packs preserve the assigned roster and answer key revision."""
import json
from pathlib import Path
import unittest
import uuid
import test_classes as classes
from utils import answer_forms, class_store, job_store, workspace_store, backup
from utils.gigachat_client import AIServiceError


class AnswerFormTests(unittest.TestCase):
    setUp = classes.ClassTests.setUp
    call = classes.ClassTests.call
    signed = classes.ClassTests.signed
    login = classes.ClassTests.login
    create = classes.ClassTests.create
    compiled = classes.ClassTests.compiled
    classroom = classes.ClassTests.classroom
    assignment = classes.ClassTests.assignment

    def test_private_endpoint_requires_csrf_owner_and_valid_mode(self):
        _, _, a, _ = self.assignment()
        url = '/api/v2/jobs/answer_forms'
        payload = {'assignment_id': a['id'], 'mode': 'class'}
        for client, expected in ((self.other, 404), (self.anon, 401)):
            self.assertEqual(self.call(client, 'post', url, json=payload).status_code, expected)
        self.assertEqual(self.call(self.client, 'post', url, json=payload, headers={'X-CSRF-Token': 'bad'}).status_code, 403)
        for mode in ('other', None, ['class']):
            self.assertEqual(self.call(self.client, 'post', url, json=dict(payload, mode=mode)).status_code, 400)

    def test_queued_pack_freezes_roster_and_is_idempotent(self):
        c, _, a, _ = self.assignment()
        key = uuid.uuid4().hex
        payload = {'assignment_id': a['id'], 'mode': 'class'}
        job, _ = job_store.submit('max:11', 'answer_forms', key, payload, require_worker=False)
        same, created = job_store.submit('max:11', 'answer_forms', key, payload, require_worker=False)
        self.assertFalse(created); self.assertEqual(job['id'], same['id'])
        c = class_store.get_class('max:11', c['id'])
        self.call(self.client, 'post', f"/api/v2/classes/{c['id']}/students", json={'count': 1, 'revision': c['revision']})
        with workspace_store.connection() as conn:
            frozen = json.loads(conn.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])['assignment']
        self.assertEqual(frozen['students'], a['students'])
        self.assertEqual(len(frozen['students']), 2)
        self.assertEqual(frozen['worksheet'], a['worksheet'])

    def test_answers_never_appear_on_form_and_tex_is_escaped(self):
        _, _, a, _ = self.assignment()
        a['title'] = r'Тест \input{secret} & 100%'
        for task in a['worksheet']['tasks']:
            task['answer'] = 'SECRET_KEY'; task['question'] = 'SECRET_QUESTION'
        source = answer_forms.form_tex(a, 'class')
        self.assertNotIn('SECRET_', source)
        self.assertNotIn(r'\input{secret}', source)
        self.assertEqual(source.count(r'\newpage'), 1)
        for s in a['students']: self.assertIn(s['code'], source)
        blank = answer_forms.form_tex(a, 'blank')
        for s in a['students']: self.assertNotIn(s['code'], blank)
        self.assertEqual(blank.count(r'\node[anchor=east'), len(a['worksheet']['tasks']))

    def test_completed_pdf_survives_job_cleanup_backup_and_is_private(self):
        _, _, a, _ = self.assignment()
        job, _ = job_store.submit('max:11', 'answer_forms', uuid.uuid4().hex, {'assignment_id': a['id'], 'mode': 'class'}, require_worker=False)
        claim = job_store.claim_next('compile')
        base = 'job_' + job['id']
        Path(self.temp.name, base + '.pdf').write_bytes(b'%PDF-fixture')
        Path(self.temp.name, base + '.tex').write_text('template', encoding='utf-8')
        self.assertTrue(job_store.complete(claim, {'ok': True}))
        result = job_store.get_job('max:11', job['id'])['result']
        self.assertEqual(self.call(self.other, 'get', result['pdf_url']).status_code, 404)
        response = self.call(self.client, 'get', result['pdf_url'])
        self.assertEqual(response.status_code, 200); response.close()
        with workspace_store.connection() as conn: conn.execute('DELETE FROM jobs WHERE id=?', (job['id'],))
        exports = class_store.get_assignment('max:11', a['id'])['answer_forms']
        self.assertEqual(exports[0]['pdf_url'], result['pdf_url'])
        archive = Path(self.temp.name, 'copy.zip'); target = Path(self.temp.name, 'restored')
        backup.create_backup(archive); backup.restore_backup(archive, target)
        self.assertTrue((target / 'generated' / (base + '.pdf')).is_file())
