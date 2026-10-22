"""Photo review boundary: keys, isolation, confirmation, zero/missing and recovery."""
import io
import json
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
import uuid

from PIL import Image
import test_classes as classes
from utils import answer_check, backup, job_store, review_store, workspace_store
from utils.gigachat_client import AIServiceError


class ReviewTests(unittest.TestCase):
    setUp = classes.ClassTests.setUp
    call = classes.ClassTests.call
    signed = classes.ClassTests.signed
    login = classes.ClassTests.login
    create = classes.ClassTests.create
    compiled = classes.ClassTests.compiled
    classroom = classes.ClassTests.classroom
    assignment = classes.ClassTests.assignment

    def photo(self, color='white'):
        target = Path(self.temp.name, color + '.jpg')
        Image.new('RGB', (150, 150), color).save(target)
        return target

    def queued(self, assignment=None, student_index=0, color='white'):
        if assignment is None:
            _, _, assignment, _ = self.assignment()
        payload = {'assignment_id': assignment['id'], 'student_id': assignment['students'][student_index]['id']}
        job, _ = job_store.submit('max:11', 'grade', uuid.uuid4().hex, payload, [self.photo(color)], require_worker=False)
        return assignment, job, payload

    def recognized(self, assignment=None, student_index=0, color='white', states=None):
        assignment, job, payload = self.queued(assignment, student_index, color)
        claim = job_store.claim_next('ai')
        directory = job_store.job_directory(job['id']) / 'pages'
        directory.mkdir()
        Image.new('RGB', (150, 150), color).save(directory / 'page_1.jpg')
        output = {'answers': [{'task_id': t['id'], 'text': t['answer'], 'state': states[i] if states else 'readable'}
                              for i, t in enumerate(assignment['worksheet']['tasks'])], 'photos': ['page_1.jpg']}
        self.assertTrue(job_store.complete(claim, output))
        return assignment, review_store.get_review('max:11', job['id'])

    def body(self, review, action='confirm', score=1):
        return {'revision': review['revision'], 'action': action, 'reviewed': True, 'comment': '',
                'answers': [{'task_id': a['task_id'], 'text': a['text'], 'score': score, 'comment': ''} for a in review['answers']]}

    def test_confirmed_zero_is_included_and_missing_pupil_is_not_zero(self):
        a, r = self.recognized()
        report = review_store.report('max:11', a['id'])
        self.assertEqual(report['summary']['submitted'], 1)
        self.assertEqual(report['summary']['not_submitted'], 1)
        self.assertIsNone(report['summary']['average'])
        review_store.update('max:11', r['id'], self.body(r, score=0))
        report = review_store.report('max:11', a['id'])
        self.assertEqual(report['summary']['confirmed'], 1)
        self.assertEqual(report['summary']['average'], 0)
        self.assertEqual(report['summary']['percent'], 0)
        self.assertEqual({s['score'] for s in report['students']}, {0, None})
        self.assertTrue(all(t['total'] == 1 and t['percent'] == 0 for t in report['tasks']))

    def test_drafts_do_not_enter_aggregate_and_corrections_have_history(self):
        a, r = self.recognized()
        r = review_store.update('max:11', r['id'], self.body(r, action='save'))
        self.assertEqual(review_store.report('max:11', a['id'])['summary']['confirmed'], 0)
        r = review_store.update('max:11', r['id'], self.body(r))
        old = self.body(r, score=0)
        r = review_store.update('max:11', r['id'], old)
        self.assertEqual(review_store.report('max:11', a['id'])['summary']['average'], 0)
        self.assertEqual([h['action'] for h in review_store.history('max:11', r['id'])], ['confirm', 'confirm', 'save', 'recognized'])
        with self.assertRaises(AIServiceError) as raised:
            review_store.update('max:11', r['id'], old)
        self.assertEqual(raised.exception.code, 'revision_conflict')
        with self.assertRaises(AIServiceError):
            review_store.update('max:11', r['id'], self.body(r, action='save'))

    def test_unreadable_blank_and_omitted_numbers_are_not_automatic_zero(self):
        _, r = self.recognized(states=['unclear', 'blank', 'readable'])
        self.assertIsNone(r['answers'][0]['score'])
        self.assertIsNone(r['answers'][1]['score'])
        self.assertEqual(r['answers'][1]['text'], '')
        tasks = r['tasks']
        parsed = review_store.validate_recognition({'answers': []}, tasks)
        self.assertTrue(all(a['state'] == 'unclear' for a in parsed))
        payload = self.body(r)
        payload['answers'][0]['score'] = None
        with self.assertRaises(AIServiceError) as raised: review_store.update('max:11', r['id'], payload)
        self.assertEqual(raised.exception.code, 'scores_incomplete')

    def test_explicit_confirmation_and_strict_score_types_required(self):
        _, r = self.recognized()
        payload = self.body(r); payload['reviewed'] = False
        self.assertEqual(self.call(self.client, 'put', '/api/v2/reviews/' + r['id'], json=payload).status_code, 400)
        for score in (True, '1', 2, -1, 0.5):
            with self.subTest(score=score), self.assertRaises(AIServiceError):
                review_store.update('max:11', r['id'], self.body(r, score=score))

    def test_all_review_and_photo_routes_are_owner_isolated(self):
        a, r = self.recognized()
        routes = [('get', '/api/v2/reviews/' + r['id']), ('get', '/api/v2/reviews/' + r['id'] + '/history'),
                  ('get', r['photos'][0]), ('put', '/api/v2/reviews/' + r['id']), ('delete', '/api/v2/reviews/' + r['id']),
                  ('get', '/api/v2/assignments/' + a['id'] + '/report'), ('get', '/api/v2/assignments/' + a['id'] + '/report.csv'),
                  ('post', '/api/v2/assignments/' + a['id'] + '/submissions')]
        for method, url in routes:
            with self.subTest(url=url, method=method):
                kwargs = {'json': self.body(r)} if method in ('put', 'delete') else {}
                if method == 'post': kwargs = {'headers': {'Idempotency-Key': uuid.uuid4().hex}, 'data': {'student_id': r['student_id']}}
                self.assertEqual(self.call(self.other, method, url, **kwargs).status_code, 404)
                self.assertEqual(self.call(self.anon, method, url, **kwargs).status_code, 401)
        photo = self.call(self.client, 'get', r['photos'][0])
        self.assertEqual(photo.status_code, 200); self.assertEqual(photo.mimetype, 'image/jpeg')
        self.assertEqual(photo.headers['Cache-Control'], 'no-store'); photo.close()
        self.assertEqual(self.call(self.client, 'put', '/api/v2/reviews/' + r['id'], json=self.body(r), headers={'X-CSRF-Token': 'wrong'}).status_code, 403)

    def test_same_request_reuses_job_but_same_photos_cannot_go_to_another_pupil(self):
        a, job, payload = self.queued()
        again, created = job_store.submit('max:11', 'grade', job['request_key'], payload, [self.photo()], require_worker=False)
        self.assertFalse(created); self.assertEqual(again['id'], job['id'])
        claim = job_store.claim_next('ai'); job_store.fail(claim['id'], claim['claim'], 'fail', 'test'); job_store.maintain()
        with self.assertRaises(AIServiceError) as raised:
            self.queued(a, 1)
        self.assertEqual(raised.exception.code, 'duplicate_submission')
        with self.assertRaises(AIServiceError) as raised:
            self.queued(a)
        self.assertEqual(raised.exception.code, 'review_exists')

    def test_foreign_assignment_and_nonmember_rejected_before_enqueuing(self):
        a, _, _ = self.queued()
        with self.assertRaises(AIServiceError):
            job_store.submit('max:22', 'grade', uuid.uuid4().hex, {'assignment_id': a['id'], 'student_id': a['students'][0]['id']}, [self.photo()], require_worker=False)
        with workspace_store.connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 1)

    def test_stale_claim_cannot_commit_or_overwrite_photo(self):
        a, job, _ = self.queued()
        claim = job_store.claim_next('ai')
        job_store.fail(claim['id'], claim['claim'], 'fail', 'test')
        self.assertFalse(job_store.complete(claim, {'answers': [], 'photos': ['page_1.jpg']}))
        self.assertFalse(review_store.photo_path(job['id'], 0).exists())
        job_store.maintain()
        self.assertEqual(review_store.get_review('max:11', job['id'])['status'], 'failed')

    def test_key_is_frozen_after_material_and_roster_changes(self):
        c, m, a, _ = self.assignment()
        a, r = self.recognized(a)
        changed = dict(m['worksheet']); changed['tasks'] = [dict(t, answer='999') for t in changed['tasks']]
        workspace_store.put_material('max:11', changed, 'manual', m['id'], revision=1)
        fresh = review_store.get_review('max:11', r['id'])
        self.assertEqual(fresh['tasks'], m['worksheet']['tasks'])
        self.assertEqual(fresh['edition_code'], a['code'])

    def test_delete_draft_then_resubmit_and_confirmed_cannot_be_removed(self):
        a, r = self.recognized()
        path = review_store.photo_path(r['id'], 0)
        review_store.remove('max:11', r['id'], r['revision'])
        self.assertFalse(path.exists())
        a, r = self.recognized(a)
        r = review_store.update('max:11', r['id'], self.body(r))
        with self.assertRaises(AIServiceError): review_store.remove('max:11', r['id'], r['revision'])

    def test_photo_expiry_removes_only_photos_preserves_confirmed_scores(self):
        a, r = self.recognized(); r = review_store.update('max:11', r['id'], self.body(r))
        path = review_store.photo_path(r['id'], 0)
        with workspace_store.connection() as conn:
            conn.execute('UPDATE reviews SET photo_expires=? WHERE id=?', (time.time() - 1, r['id']))
        job_store.maintain()
        self.assertFalse(path.exists())
        self.assertEqual(review_store.get_review('max:11', r['id'])['photos'], [])
        self.assertEqual(review_store.report('max:11', a['id'])['summary']['confirmed'], 1)

    def test_backup_restores_private_photos_and_never_replays_pending_review(self):
        a, r = self.recognized(); a, pending, _ = self.queued(a, 1, 'blue')
        archive = Path(self.temp.name, 'reviews.zip'); target = Path(self.temp.name, 'restored')
        backup.create_backup(archive); backup.restore_backup(archive, target)
        self.assertEqual((target / 'review_photos' / r['id'] / '0.jpg').read_bytes(), review_store.photo_path(r['id'], 0).read_bytes())
        conn = sqlite3.connect(target / 'worksheets.db')
        try:
            self.assertEqual(conn.execute('SELECT status FROM reviews WHERE id=?', (pending['id'],)).fetchone()[0], 'failed')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        finally: conn.close()

    def test_csv_preserves_zero_and_blank_missing_and_escapes_spreadsheet_formulas(self):
        a, r = self.recognized(); review_store.update('max:11', r['id'], self.body(r, score=0))
        with workspace_store.connection() as conn: conn.execute("UPDATE assignments SET title='=cmd' WHERE id=?", (a['id'],))
        text = review_store.csv_report('max:11', a['id'])
        self.assertIn("'=cmd", text); self.assertIn(';0;3;', text); self.assertIn(';Не сдал;;3;', text)

    def test_numeric_hints_are_conservative_and_do_not_execute_expressions(self):
        self.assertEqual(answer_check.hint('$\\frac{1}{2}$', '0,5', 'readable')['suggested_score'], 1)
        self.assertEqual(answer_check.hint('$x=6$', '6', 'readable')['suggested_score'], 1)
        for expected, observed in [('6', '7'), ('1 м', '100 см'), ('', ''), ('5', '__import__("os")')]:
            self.assertIsNone(answer_check.hint(expected, observed, 'readable')['suggested_score'])
        self.assertIsNone(answer_check.hint('5', '5', 'unclear')['suggested_score'])

    def test_invalid_ai_ids_duplicates_and_codes_fail_as_validation_errors(self):
        _, r = self.recognized()
        for values in [[{'task_id': [], 'text': '', 'state': 'blank'}],
                       [{'task_id': r['tasks'][0]['id'], 'text': '5', 'state': 'readable'}] * 2]:
            with self.assertRaises(AIServiceError): review_store.validate_recognition({'answers': values}, r['tasks'])

    def test_real_upload_endpoint_enqueues_and_rejects_bad_format(self):
        _, _, a, _ = self.assignment(); job_store.heartbeat('test', 'ai')
        url = '/api/v2/assignments/' + a['id'] + '/submissions'
        with patch('review_api.get_ai_status', return_value={'ai_ready': True}):
            invalid = self.call(self.client, 'post', url, headers={'Idempotency-Key': uuid.uuid4().hex},
                                data={'student_id': a['students'][0]['id'], 'files': (io.BytesIO(b'not photo'), 'x.jpg')})
            self.assertEqual(invalid.status_code, 415)
            with self.photo().open('rb') as image:
                result = self.call(self.client, 'post', url, headers={'Idempotency-Key': uuid.uuid4().hex},
                                   data={'student_id': a['students'][0]['id'], 'files': (image, 'x.jpg')})
            self.assertEqual(result.status_code, 202, result.json)
            self.assertEqual(result.json['job']['kind'], 'grade')
            self.assertEqual(review_store.get_review('max:11', result.json['review_id'])['status'], 'processing')

    def test_recognition_transport_never_receives_question_or_answer_key(self):
        from utils import grading_ai
        client = Mock()
        client.chat.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(
            {'answers': [{'task_id': 'a', 'text': '6', 'state': 'readable'}]})))])
        factory = Mock(); factory.__enter__ = Mock(return_value=client); factory.__exit__ = Mock(return_value=False)
        with patch.object(grading_ai, '_create_client', return_value=factory):
            result = grading_ai.recognize([{'id': 'a', 'question': 'SECRET_QUESTION', 'answer': 'SECRET_KEY'}], [])
        content = '\n'.join(m.content for m in client.chat.call_args.args[0].messages)
        self.assertNotIn('SECRET_QUESTION', content); self.assertNotIn('SECRET_KEY', content)
        self.assertEqual(result['answers'][0]['text'], '6')

    def test_recognition_format_retry_is_bounded(self):
        from utils import grading_ai
        client = Mock()
        client.chat.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='not json'))])
        factory = Mock(); factory.__enter__ = Mock(return_value=client); factory.__exit__ = Mock(return_value=False)
        with patch.object(grading_ai, '_create_client', return_value=factory), self.assertRaises(AIServiceError):
            grading_ai.recognize([{'id': 'a'}], [])
        self.assertEqual(client.chat.call_count, 2)

    def test_teacher_edit_recomputes_hint_without_changing_explicit_grade(self):
        a, r = self.recognized()
        payload = self.body(r, action='save', score=0)
        payload['answers'][0]['text'] = 'Definitely not the expected answer'
        saved = review_store.update('max:11', r['id'], payload)
        self.assertEqual(saved['answers'][0]['score'], 0)
        self.assertTrue(saved['answers'][0]['teacher_edited'])
        self.assertEqual(saved['answers'][0]['comparison'], 'manual')
        self.assertIsNone(saved['answers'][0]['suggested_score'])

    def test_restart_recovers_finished_recognition_without_provider_replay(self):
        a, job, _ = self.queued()
        claim = job_store.claim_next('ai')
        directory = job_store.job_directory(job['id'])
        (directory / 'pages').mkdir()
        Image.new('RGB', (150, 150), 'white').save(directory / 'pages/page_1.jpg')
        (directory / 'result.json').write_text(json.dumps({'answers': [], 'photos': ['page_1.jpg']}), encoding='utf-8')
        with workspace_store.connection() as conn:
            conn.execute('UPDATE jobs SET heartbeat=? WHERE id=?', (time.time() - 100, job['id']))
        job_store.maintain()
        self.assertEqual(job_store.get_job('max:11', job['id'])['status'], 'succeeded')
        r = review_store.get_review('max:11', job['id'])
        self.assertEqual(r['status'], 'needs_review')
        self.assertTrue(review_store.photo_path(job['id'], 0).is_file())
        self.assertTrue(all(answer['score'] is None for answer in r['answers']))
        self.assertFalse(job_store.complete(claim, {'answers': [], 'photos': ['page_1.jpg']}))


if __name__ == '__main__': unittest.main()
