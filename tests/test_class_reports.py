"""Class-wide reports keep per-work denominators, fixed rosters and owner privacy."""
import json
import unittest
import uuid

import test_reviews as reviews
from utils import class_report, class_store, review_store, workspace_store
from utils.worksheet import validate_worksheet


class ClassReportTests(unittest.TestCase):
    setUp = reviews.ReviewTests.setUp
    call = reviews.ReviewTests.call
    signed = reviews.ReviewTests.signed
    login = reviews.ReviewTests.login
    create = reviews.ReviewTests.create
    compiled = reviews.ReviewTests.compiled
    classroom = reviews.ReviewTests.classroom
    assignment = reviews.ReviewTests.assignment
    photo = reviews.ReviewTests.photo
    queued = reviews.ReviewTests.queued
    recognized = reviews.ReviewTests.recognized
    body = reviews.ReviewTests.body

    def another(self, c, *, date='', subject='physics', count=1, title='Оптика · итог'):
        material = self.create()
        sheet = dict(material['worksheet'], subject=subject, title=title)
        sheet['tasks'] = sheet['tasks'][:count]
        material = workspace_store.put_material('max:11', validate_worksheet(sheet), 'manual', material['id'], material['revision'])
        material, edition = self.compiled(material)
        c = class_store.get_class('max:11', c['id'])
        assignment, _ = class_store.assign('max:11', c['id'], {'revision': c['revision'], 'edition_id': edition,
            'title': title + ' · назначение', 'scheduled_date': date, 'request_key': uuid.uuid4().hex})
        return material, assignment

    def test_distinct_work_maxima_and_zero_are_not_pooled(self):
        c, _, first, _ = self.assignment()
        first, r = self.recognized(first)
        review_store.update('max:11', r['id'], self.body(r, score=0))
        _, second = self.another(c, date='2026-10-23')
        second, r = self.recognized(second, color='blue')
        review_store.update('max:11', r['id'], self.body(r, score=1))
        data = class_report.overview('max:11', c['id'], {})
        self.assertEqual([w['assignment_id'] for w in data['works']], [second['id'], first['id']])
        summaries = {w['assignment_id']: w['summary'] for w in data['works']}
        self.assertEqual((summaries[first['id']]['average'], summaries[first['id']]['maximum'], summaries[first['id']]['percent']), (0, 3, 0))
        self.assertEqual((summaries[second['id']]['average'], summaries[second['id']]['maximum'], summaries[second['id']]['percent']), (1, 1, 100))
        self.assertEqual(data['totals']['confirmed'], 2)
        self.assertEqual(data['totals']['total'], 4)  # assignments to pupils, not 4 unique pupils
        self.assertNotIn('average', data['totals']); self.assertNotIn('percent', data['totals'])
        for work in data['works']:
            self.assertEqual(work['summary'], review_store.report('max:11', work['assignment_id'])['summary'])

    def test_unconfirmed_work_and_pending_correction_keep_official_scores(self):
        c, _, first, _ = self.assignment()
        first, r = self.recognized(first)
        r = review_store.update('max:11', r['id'], self.body(r))
        review_store.save_draft('max:11', r['id'], self.body(r, score=0))
        first, pending = self.recognized(first, student_index=1, color='blue', states=['unclear', 'blank', 'readable'])
        data = class_report.overview('max:11', c['id'], {'student_id': r['student_id']})
        work = data['works'][0]
        self.assertEqual(work['summary']['confirmed'], 1)
        self.assertEqual(work['summary']['needs_review'], 1)
        self.assertEqual(work['summary']['average'], 3)
        self.assertEqual(work['summary']['pending_corrections'], 1)
        self.assertEqual(work['student_result']['score'], 3)
        data = class_report.overview('max:11', c['id'], {'student_id': pending['student_id']})
        self.assertIsNone(data['works'][0]['student_result']['score'])
        self.assertEqual(data['works'][0]['student_result']['status'], 'needs_review')

    def test_later_pupil_is_not_a_missing_submission_and_archived_pupil_is_retained(self):
        c, _, first, _ = self.assignment()
        c = class_store.get_class('max:11', c['id'])
        original = c['students'][0]
        c = class_store.update_student('max:11', c['id'], original['id'], {'revision': c['revision'], 'archived': True})
        previous_ids = {s['id'] for s in c['students']}
        c = class_store.add_students('max:11', c['id'], {'revision': c['revision'], 'count': 1})
        added = next(s for s in c['students'] if s['id'] not in previous_ids)
        _, second = self.another(c, date='2026-10-24')
        data = class_report.overview('max:11', c['id'], {'student_id': added['id']})
        works = {w['assignment_id']: w for w in data['works']}
        self.assertEqual(works[first['id']]['student_result']['status'], 'not_assigned')
        self.assertIsNone(works[first['id']]['student_result']['score'])
        self.assertEqual(works[first['id']]['summary']['total'], 2)
        self.assertEqual(works[second['id']]['student_result']['status'], 'not_submitted')
        self.assertEqual(works[second['id']]['summary']['total'], 2)
        data = class_report.overview('max:11', c['id'], {'student_id': original['id']})
        self.assertTrue(data['selected_student']['archived'])
        works = {w['assignment_id']: w for w in data['works']}
        self.assertEqual(works[first['id']]['student_result']['status'], 'not_submitted')
        self.assertEqual(works[second['id']]['student_result']['status'], 'not_assigned')

    def test_filters_use_conducted_date_not_due_date_and_keep_closed_and_undated(self):
        c, _, first, _ = self.assignment()  # undated, due November 6
        _, second = self.another(c, date='2026-10-23')
        _, third = self.another(c, date='2026-10-24', subject='math', title='Проценты')
        class_store.update_assignment('max:11', second['id'], {'revision': second['revision'], 'status': 'closed'})
        data = class_report.overview('max:11', c['id'], {})
        self.assertEqual(data['totals']['works'], 3); self.assertEqual(data['totals']['undated'], 1)
        self.assertEqual(data['works'][-1]['assignment_id'], first['id'])
        data = class_report.overview('max:11', c['id'], {'from_date': '2026-10-23', 'to_date': '2026-10-23'})
        self.assertEqual([w['assignment_id'] for w in data['works']], [second['id']])
        self.assertEqual(data['works'][0]['status'], 'closed')
        self.assertEqual(data['available_work_count'], 3)
        data = class_report.overview('max:11', c['id'], {'subject': 'math', 'status': 'active'})
        self.assertEqual({w['assignment_id'] for w in data['works']}, {first['id'], third['id']})
        self.assertEqual(class_report.overview('max:11', c['id'], {'from_date': '2026-11-06'})['works'], [])

    def test_frozen_topic_and_subject_search_without_leaking_keys_or_comments(self):
        c, material, first, _ = self.assignment()
        first, r = self.recognized(first)
        payload = self.body(r); payload['comment'] = 'PRIVATE_TEACHER_COMMENT'
        review_store.update('max:11', r['id'], payload)
        sheet = dict(material['worksheet'], subject='physics', title='ПОДМЕНЁННАЯ ТЕМА', teacher_name='PRIVATE_TEACHER_NAME')
        sheet['tasks'] = [dict(t, answer='PRIVATE_KEY') for t in sheet['tasks']]
        workspace_store.put_material('max:11', sheet, 'manual', material['id'], material['revision'])
        data = class_report.overview('max:11', c['id'], {'q': material['worksheet']['title'].upper(), 'subject': 'math'})
        self.assertEqual(len(data['works']), 1)
        self.assertEqual(data['works'][0]['topic'], material['worksheet']['title'])
        text = json.dumps(data)
        for private in ('PRIVATE_TEACHER_COMMENT', 'PRIVATE_TEACHER_NAME', 'PRIVATE_KEY', 'teacher_name', 'answers', 'photos'):
            self.assertNotIn(private, text)

    def test_owner_and_selected_pupil_are_scoped_to_class(self):
        c, _, _, _ = self.assignment()
        other = self.classroom('Другой класс', ['Синтетический ученик'])
        url = '/api/v2/classes/' + c['id'] + '/report'
        self.assertEqual(self.call(self.anon, 'get', url).status_code, 401)
        self.assertEqual(self.call(self.other, 'get', url).status_code, 404)
        self.assertEqual(self.call(self.client, 'get', url + '?student_id=' + other['students'][0]['id']).status_code, 404)
        result = self.call(self.client, 'get', url)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.headers['Cache-Control'], 'no-store')
        self.assertTrue(all('name' not in pupil for pupil in result.json['report']['students']))

    def test_empty_class_and_invalid_period_are_explicit(self):
        c = self.classroom()
        url = '/api/v2/classes/' + c['id'] + '/report'
        data = self.call(self.client, 'get', url).json['report']
        self.assertEqual(data['works'], []); self.assertEqual(data['totals']['total'], 0)
        for query in ('from_date=2026-02-30', 'from_date=2026-10-24&to_date=2026-10-23', 'subject=chemistry', 'status=deleted', 'q=' + 'x'*161):
            self.assertEqual(self.call(self.client, 'get', url + '?' + query).status_code, 400)
