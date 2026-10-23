"""Exports freeze official results and preserve private ownership and empty scores."""
from contextlib import closing
import csv
import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import uuid

import test_class_reports as reports
from utils import backup, class_report, class_store, job_store, job_runner, report_export, review_store, workspace_store


class ReportExportTests(unittest.TestCase):
    setUp = reports.ClassReportTests.setUp
    call = reports.ClassReportTests.call
    signed = reports.ClassReportTests.signed
    login = reports.ClassReportTests.login
    create = reports.ClassReportTests.create
    compiled = reports.ClassReportTests.compiled
    classroom = reports.ClassReportTests.classroom
    assignment = reports.ClassReportTests.assignment
    photo = reports.ClassReportTests.photo
    queued = reports.ClassReportTests.queued
    recognized = reports.ClassReportTests.recognized
    body = reports.ClassReportTests.body
    another = reports.ClassReportTests.another

    def export_job(self, assignment):
        return job_store.submit('max:11', 'report_pdf', uuid.uuid4().hex, {'assignment_id': assignment['id']}, require_worker=False)[0]

    def finish_pdf(self, job):
        claim = job_store.claim_next('compile')
        self.assertEqual(claim['id'], job['id'])
        Path(self.temp.name, 'job_' + job['id'] + '.pdf').write_bytes(b'%PDF-1.4\nfixture')
        Path(self.temp.name, 'job_' + job['id'] + '.tex').write_text('Trusted fixture', encoding='utf-8')
        self.assertTrue(job_store.complete(claim, {'ok':True}))
        return job_store.get_job('max:11', job['id'])['result']

    def test_pdf_snapshot_is_immutable_and_retry_keeps_original_scores(self):
        a, r = self.recognized()
        r = review_store.update('max:11', r['id'], self.body(r))
        job = self.export_job(a)
        with workspace_store.connection() as conn:
            payload = json.loads(conn.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
        self.assertEqual(payload['report']['summary']['average'], 3)
        review_store.update('max:11', r['id'], self.body(r, score=0))
        same, created = job_store.submit('max:11', 'report_pdf', job['request_key'], {'assignment_id':a['id']}, require_worker=False)
        self.assertFalse(created); self.assertEqual(same['id'], job['id'])
        with workspace_store.connection() as conn:
            fresh = json.loads(conn.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
        self.assertEqual(fresh, payload)
        self.assertEqual(review_store.report('max:11', a['id'])['summary']['average'], 0)
        result = self.finish_pdf(job)
        self.assertEqual(result['generated_at'], payload['report']['generated_at'])
        self.assertIsNone(result['keys_url']); self.assertIsNone(result['marp_url'])
        with workspace_store.connection() as conn:
            self.assertIsNone(conn.execute('SELECT id FROM editions WHERE id=?', (job['id'],)).fetchone())

    def test_report_route_requires_owner_csrf_key_and_compiler_worker(self):
        _, _, a, _ = self.assignment()
        url, payload = '/api/v2/jobs/report_pdf', {'assignment_id':a['id']}
        headers = {'Idempotency-Key':uuid.uuid4().hex}
        self.assertEqual(self.call(self.other, 'post', url, json=payload, headers=headers).status_code, 404)
        self.assertEqual(self.call(self.anon, 'post', url, json=payload, headers=headers).status_code, 401)
        self.assertEqual(self.call(self.client, 'post', url, json=payload, headers=dict(headers, **{'X-CSRF-Token':'wrong'})).status_code, 403)
        self.assertEqual(self.call(self.client, 'post', url, json=payload).status_code, 400)
        job_store.heartbeat('test-ai', 'ai')
        self.assertEqual(self.call(self.client, 'post', url, json=payload, headers=headers).status_code, 503)
        job_store.heartbeat('test-compile', 'compile')
        self.assertEqual(self.call(self.client, 'post', url, json=dict(payload, report={'score':999}), headers=headers).status_code, 400)
        accepted = self.call(self.client, 'post', url, json=payload, headers=headers)
        self.assertEqual(accepted.status_code, 202, accepted.json)
        self.assertEqual(self.call(self.client, 'post', url, json=payload, headers=headers).json['job']['id'], accepted.json['job']['id'])

    def test_assignment_csv_has_only_official_per_task_scores_and_dates(self):
        a, r = self.recognized()
        payload = self.body(r, score=0)
        payload['answers'][0].update(text='PRIVATE_TRANSCRIPTION', comment='PRIVATE_TASK_COMMENT')
        payload['comment'] = 'PRIVATE_WORK_COMMENT'
        r = review_store.update('max:11', r['id'], payload)
        review_store.save_draft('max:11', r['id'], self.body(r, score=1))
        text = review_store.csv_report('max:11', a['id'])
        rows = list(csv.DictReader(io.StringIO(text.lstrip('\ufeff')), delimiter=';'))
        confirmed = next(row for row in rows if row['Статус']=='Подтверждено')
        missing = next(row for row in rows if row['Статус']=='Не сдал')
        self.assertEqual(confirmed['Баллы'], '0')
        self.assertEqual([confirmed[f'Задание {i}'] for i in range(1,4)], ['0']*3)
        self.assertEqual(confirmed['Черновик исправлений'], 'Да')
        self.assertEqual(confirmed['Сдать до'], '2026-11-06')
        self.assertTrue(confirmed['Сформирован'])
        self.assertEqual(missing['Баллы'], '')
        self.assertEqual([missing[f'Задание {i}'] for i in range(1,4)], ['']*3)
        for private in ('PRIVATE_TRANSCRIPTION', 'PRIVATE_TASK_COMMENT', 'PRIVATE_WORK_COMMENT'):
            self.assertNotIn(private, text)

    def test_filtered_overview_csv_preserves_not_assigned_and_empty_and_zero(self):
        c, _, a, _ = self.assignment()
        a, r = self.recognized(a)
        review_store.update('max:11', r['id'], self.body(r, score=0))
        c = class_store.get_class('max:11', c['id']); old = {s['id'] for s in c['students']}
        c = class_store.add_students('max:11', c['id'], {'revision':c['revision'],'count':1})
        added = next(s for s in c['students'] if s['id'] not in old)
        self.another(c, date='2026-10-23')
        data = class_report.overview('max:11', c['id'], {'student_id':added['id']})
        rows = list(csv.DictReader(io.StringIO(report_export.overview_csv(data).lstrip('\ufeff')), delimiter=';'))
        self.assertEqual({row['Статус ученика'] for row in rows}, {'Не назначалась','Не сдал'})
        self.assertTrue(all(row['Баллы ученика']=='' for row in rows))
        self.assertEqual(next(row for row in rows if row['Максимум']=='3')['Средний балл'], '0,0')
        url = '/api/v2/classes/' + c['id'] + '/report.csv?subject=physics'
        response = self.call(self.client, 'get', url)
        self.assertEqual(response.status_code, 200); self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(len(list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip('\ufeff')), delimiter=';'))),1)
        self.assertEqual(self.call(self.other, 'get', url).status_code, 404)
        self.assertEqual(self.call(self.anon, 'get', url).status_code, 401)

    def test_csv_escapes_leading_whitespace_formulas_without_changing_zero(self):
        text = report_export.csv_text([[' =1+1','\t=HYPERLINK(1)','  @SUM(1)','-1',0,None]])
        cells = next(csv.reader(io.StringIO(text.lstrip('\ufeff')), delimiter=';'))
        self.assertTrue(all(cell.startswith("'") for cell in cells[:4]))
        self.assertEqual(cells[4:], ['0',''])

    def test_tex_template_cannot_execute_user_commands_and_omits_keys_and_comments(self):
        a, r = self.recognized()
        data = review_store.report('max:11', a['id'])
        data['title'] = r'\input{PRIVATE_FILE}&% # _ $'
        data['tasks'][0]['question'] = 'PRIVATE_QUESTION'
        text = report_export.report_tex(data)
        self.assertNotIn(r'\input{PRIVATE_FILE}', text)
        self.assertIn(r'\textbackslash{}input\{PRIVATE\_FILE\}', text)
        self.assertNotIn('PRIVATE_QUESTION', text)
        self.assertIn('fonts/', text); self.assertIn(r'\pageref{LastPage}', text)
        self.assertIn('Прочерк означает', text)

    def test_compiler_execution_does_not_call_recognition_or_generation(self):
        _, _, a, _ = self.assignment()
        job = self.export_job(a); job_store.claim_next('compile')
        with patch('utils.report_export.compile_report') as compile_pdf, patch('utils.ai_batch.generate') as generate, patch('utils.grading_ai.recognize') as recognize:
            self.assertEqual(job_runner.execute(job['id']), 0)
        compile_pdf.assert_called_once(); generate.assert_not_called(); recognize.assert_not_called()
        self.assertEqual(json.loads((job_store.job_directory(job['id'])/'result.json').read_text(encoding='utf-8')), {'ok':True})

    def test_report_files_are_private_and_restored_with_backup(self):
        _, _, a, _ = self.assignment()
        job = self.export_job(a); result = self.finish_pdf(job)
        for key in ('pdf_url','tex_url'):
            self.assertEqual(self.call(self.other, 'get', result[key]).status_code, 404)
            self.assertEqual(self.call(self.anon, 'get', result[key]).status_code, 401)
            response = self.call(self.client, 'get', result[key]); self.assertEqual(response.status_code, 200); response.close()
        export = self.call(self.client, 'post', '/api/v2/exports/' + job['id'])
        self.assertEqual(export.status_code, 200)
        self.assertEqual(set(export.json), {'pdf_url','tex_url','expires_at'})
        response = self.call(self.anon, 'get', export.json['pdf_url']); self.assertEqual(response.status_code,200); response.close()
        archive, destination = Path(self.temp.name,'report.zip'), Path(self.temp.name,'restored-report')
        backup.create_backup(archive); backup.restore_backup(archive, destination)
        self.assertTrue((destination/'generated'/('job_'+job['id']+'.pdf')).is_file())
        with closing(sqlite3.connect(destination/'worksheets.db')) as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
