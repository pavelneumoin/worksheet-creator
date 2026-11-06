import json
import unittest
import uuid
from unittest.mock import patch
import test_reviews as reviews
from utils import school_store,analytics,analytics_ai,analytics_export,review_store,workspace_store,job_store
from utils.gigachat_client import AIServiceError

class SchoolTests(unittest.TestCase):
    setUp=reviews.ReviewTests.setUp
    call=reviews.ReviewTests.call
    signed=reviews.ReviewTests.signed
    login=reviews.ReviewTests.login
    create=reviews.ReviewTests.create
    compiled=reviews.ReviewTests.compiled
    classroom=reviews.ReviewTests.classroom
    assignment=reviews.ReviewTests.assignment
    queued=reviews.ReviewTests.queued
    recognized=reviews.ReviewTests.recognized
    photo=reviews.ReviewTests.photo
    body=reviews.ReviewTests.body

    def school(self):return school_store.create('max:22',{'name':'Школа тестирования'})
    def joined(self):
        school=self.school();invite=school_store.invite('max:22')
        school_store.join('max:11',{'code':invite['code'],'share_statistics':True})
        return school

    def test_invitation_requires_consent_is_single_use_and_cannot_make_admin(self):
        self.school();token=school_store.invite('max:22')['code']
        with self.assertRaises(AIServiceError):school_store.join('max:11',{'code':token})
        result=school_store.join('max:11',{'code':token,'share_statistics':True,'role':'admin'})
        self.assertEqual(result['role'],'teacher')
        self.login(self.anon,33)
        with self.assertRaises(AIServiceError):school_store.join('max:33',{'code':token,'share_statistics':True})
        self.assertEqual(self.call(self.client,'post','/api/v2/school/invites').status_code,403)
        self.assertEqual(self.call(self.client,'get','/api/v2/analytics?scope=school').status_code,403)

    def test_school_does_not_see_unjoined_or_departed_teacher_results(self):
        a,r=self.recognized();review_store.update('max:11',r['id'],self.body(r,score=1))
        self.school()
        self.assertEqual(analytics.overview('max:22',{'scope':'school'})['totals']['confirmed'],0)
        token=school_store.invite('max:22')['code'];school_store.join('max:11',{'code':token,'share_statistics':True})
        report=analytics.overview('max:22',{'scope':'school'})
        self.assertEqual(report['totals']['confirmed'],1)
        self.assertNotIn('answers',json.dumps(report));self.assertNotIn('photos',json.dumps(report))
        school_store.leave('max:11')
        self.assertEqual(analytics.overview('max:22',{'scope':'school'})['totals']['confirmed'],0)
        self.assertEqual(analytics.overview('max:11',{})['totals']['confirmed'],1)

    def test_zero_is_counted_missing_and_draft_are_not_and_topic_is_editable(self):
        a,r=self.recognized();review_store.update('max:11',r['id'],self.body(r,score=0))
        data=analytics.overview('max:11',{})
        self.assertEqual((data['totals']['percent'],data['totals']['confirmed'],data['totals']['not_submitted']),(0,1,1))
        response=self.call(self.client,'put',f"/api/v2/assignments/{a['id']}/topic",json={'revision':a['revision'],'topic':'Квадратные уравнения'})
        self.assertEqual(response.status_code,200,response.json)
        filtered=analytics.overview('max:11',{'q':'квадратные'})
        self.assertEqual(filtered['topics'][0]['topic'],'Квадратные уравнения')
        self.assertEqual(self.call(self.other,'put',f"/api/v2/assignments/{a['id']}/topic",json={'revision':2,'topic':'Чужая тема'}).status_code,404)
        facts=analytics_ai.observations(filtered)
        self.assertIn('0,0% выполнения',facts[1])
        self.assertIn('число работ, а не уникальных учеников',facts[0])

    def test_filters_and_downloads_preserve_scope_and_csv_escapes_formulas(self):
        a,r=self.recognized();review_store.update('max:11',r['id'],self.body(r))
        self.assertEqual(self.call(self.other,'get','/api/v2/analytics?class_id='+a['class_id']).status_code,404)
        self.assertEqual(self.call(self.anon,'get','/api/v2/analytics.csv').status_code,401)
        self.assertEqual(self.call(self.client,'get','/api/v2/analytics?scope=admin').status_code,400)
        report=analytics.overview('max:11',{});report['students'][0]['topic']='=BAD()'
        self.assertIn("'=BAD()",analytics.csv_export(report))
        self.assertNotIn(r'\input',analytics_export.document(dict(report,title=r'\input{secret}')))

    def test_school_owner_cannot_be_removed_and_members_cannot_remove_others(self):
        self.joined()
        self.assertEqual(self.call(self.client,'delete','/api/v2/school/members/max:22').status_code,403)
        with self.assertRaises(AIServiceError):school_store.leave('max:22')
        school_store.leave('max:22','max:11')
        self.assertIsNone(school_store.current('max:11'))

    def test_pdf_snapshot_and_insight_hash_reject_stale_recommendations(self):
        a,r=self.recognized();review_store.update('max:11',r['id'],self.body(r))
        report=analytics.overview('max:11',{});digest=analytics_ai.digest(report)
        with workspace_store.connection() as conn:conn.execute('INSERT INTO analytics_insights VALUES(?,?,?,?,?)',('test-insight','max:11',digest,json.dumps({'observations':['Наблюдение'],'actions':['Повторить']}),'2026-11-06'))
        job,_=job_store.submit('max:11','analytics_pdf',uuid.uuid4().hex,{'filters':{},'insight_id':'test-insight'},require_worker=False)
        with workspace_store.connection() as conn:
            payload=json.loads(conn.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
        self.assertEqual(payload['report']['totals']['confirmed'],1);self.assertIn('insight',payload['report'])
        job_store.cancel('max:11',job['id'])
        with workspace_store.connection() as conn:conn.execute('UPDATE assignments SET topic=? WHERE id=?',('Новая тема',a['id']))
        with self.assertRaises(AIServiceError) as exc:job_store.submit('max:11','analytics_pdf',uuid.uuid4().hex,{'filters':{},'insight_id':'test-insight'},require_worker=False)
        self.assertEqual(exc.exception.code,'insight_stale')

if __name__=='__main__':unittest.main()
